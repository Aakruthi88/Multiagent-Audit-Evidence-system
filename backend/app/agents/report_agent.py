"""
ReportAgent - backend/app/agents/report_agent.py
-------------------------------------------------
Generates grounded audit reports with actual document evidence (Invoice, PO, GRN, Bank Statement).

Nodes:
- report_summary_node(state)  - clean or warning-only bundles
- report_detailed_node(state) - anomaly / critical bundles
- report_not_found_node(state)- missing/invalid bundle or errors
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.agents.state import BundleState
from app.core.config import settings
from app.core.logging import logger
from app.agents.llm_rules import GROUNDING_RULES
from app.db.session import SessionLocal
from app.models.models import (
    AgentExecutionLog, Report, VerificationRun, AuditBundle,
    Invoice, PurchaseOrder, GRN, Vendor, BankTransaction
)

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, None: 4}

def _sort_by_severity(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda x: _SEVERITY_ORDER.get(x.get("severity"), 4))

def _persist_report(db, run_id: Optional[str], report_json: Dict[str, Any]) -> Optional[str]:
    """Write report to reports table; return report_id string."""
    if not run_id:
        return None
    try:
        report = Report(
            run_id=run_id,
            format="json",
            content_json=report_json,
            generated_at=datetime.now(timezone.utc),
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return str(report.report_id)
    except Exception as exc:
        logger.warning(f"[ReportAgent] Failed to persist report: {exc}")
        db.rollback()
        return None

def _get_bundle_evidence(db, bundle_id: Optional[str]) -> Dict[str, Any]:
    """Fetch full grounding evidence (Invoice, PO, GRN, Bank Txn, Vendor) from DB."""
    evidence = {
        "bundle_id": str(bundle_id) if bundle_id else None,
        "invoice": None,
        "purchase_order": None,
        "grn": None,
        "bank_statement": None,
        "vendor": None,
    }
    if not bundle_id:
        return evidence

    try:
        # Invoice & Vendor
        inv = db.query(Invoice).filter(Invoice.bundle_id == bundle_id).first()
        if inv:
            vendor_name = None
            if inv.vendor_id:
                v = db.query(Vendor).filter(Vendor.vendor_id == inv.vendor_id).first()
                if v:
                    vendor_name = v.name_normalized or v.raw_name
                    evidence["vendor"] = vendor_name

            evidence["invoice"] = {
                "invoice_number": inv.invoice_number,
                "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
                "total_amount": float(inv.total_amount) if inv.total_amount is not None else None,
                "tax_amount": float(inv.tax_amount) if inv.tax_amount is not None else None,
                "vendor_name": vendor_name,
            }

            # Bank payment lookup
            bt = db.query(BankTransaction).filter(
                BankTransaction.extracted_invoice_number.ilike(f"%{inv.invoice_number}%")
            ).first()
            if not bt:
                bt = db.query(BankTransaction).filter(
                    BankTransaction.description_raw.ilike(f"%{inv.invoice_number}%")
                ).first()
            if bt:
                evidence["bank_statement"] = {
                    "payment_status": "confirmed",
                    "payment_date": str(bt.txn_date) if bt.txn_date else None,
                    "payment_amount": float(bt.debit_amount or bt.credit_amount or 0),
                    "bank_reference": bt.extracted_ref or "",
                    "description": bt.description_raw or "",
                }
            else:
                evidence["bank_statement"] = {
                    "payment_status": "NOT FOUND - no bank statement transaction record exists for this invoice",
                    "payment_date": None,
                    "payment_amount": None,
                    "bank_reference": None,
                }

        # Purchase Order
        po = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == bundle_id).first()
        if po:
            evidence["purchase_order"] = {
                "po_number": po.po_number,
                "po_date": str(po.po_date) if po.po_date else None,
                "total_amount": float(po.total_amount) if po.total_amount is not None else None,
            }
            if not evidence["vendor"] and po.vendor_id:
                v = db.query(Vendor).filter(Vendor.vendor_id == po.vendor_id).first()
                if v:
                    evidence["vendor"] = v.name_normalized or v.raw_name

        # GRN
        grn = db.query(GRN).filter(GRN.bundle_id == bundle_id).first()
        if grn:
            evidence["grn"] = {
                "grn_number": grn.grn_number,
                "grn_date": str(grn.grn_date) if grn.grn_date else None,
                "delivery_note_number": grn.delivery_note_number,
                "received_condition": grn.received_condition,
            }
    except Exception as exc:
        logger.warning(f"[ReportAgent] Error fetching evidence for bundle {bundle_id}: {exc}")

    return evidence

_NARRATIVE_SYSTEM = GROUNDING_RULES + """
You are an enterprise audit report writer for a Big-4 accounting firm.
Write a clear, professional audit narrative (2-4 paragraphs) for an audit bundle.
Ground every statement strictly in the provided document evidence and verification checks.
Cite specific document numbers (Invoice #, PO #, GRN #), amounts (in ₹ / Rs. / INR), vendor names, bank payment details (reference/date), and verification check outcomes.

CRITICAL FINANCIAL GROUNDING RULES:
1. NEVER alter, round, recalculate, drop digits from, or invent monetary amounts.
2. If Invoice Total is ₹130,390.00 and Payment Amount is ₹130,390.00, cite EXACTLY ₹130,390.00. NEVER say ₹13,039.00 or ₹13,03,900.00.
3. Use the exact verified monetary amounts provided in the Verified Financial Totals section.

CRITICAL INSTRUCTION: Do NOT include any thinking process, analysis steps, or introductory text. Return ONLY the final audit narrative text directly."""

def _clean_narrative_text(raw_text: str) -> str:
    """Strip model thinking process or preambles from response text."""
    if not raw_text:
        return ""
    text = raw_text.strip()
    if "thinking process" in text.lower():
        parts = text.split("\n\n")
        non_thinking = [p for p in parts if "thinking process" not in p.lower() and not re.match(r"^\d+\.\s+\*\*", p.strip())]
        if non_thinking:
            text = "\n\n".join(non_thinking).strip()
    text = re.sub(r"^```(?:markdown|text)?\n?", "", text, flags=re.I)
    text = re.sub(r"\n?```$", "", text, flags=re.I)
    return text.strip()

def _enforce_monetary_integrity(narrative: str, evidence: Dict[str, Any]) -> str:
    """Ensure all monetary figures in the narrative match verified evidence amounts with 100% fidelity.
    Corrects LLM quantization, rounding, or scaling errors (e.g. 13,039 or 13,03,900 instead of 130,390.00)."""
    if not narrative:
        return narrative

    ground_truth = []
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    bank = evidence.get("bank_statement") or {}

    for obj in (inv, po, bank):
        for k in ("total_amount", "payment_amount", "subtotal", "tax_amount"):
            val = obj.get(k)
            if val is not None and isinstance(val, (int, float)) and val > 0:
                ground_truth.append(float(val))

    if not ground_truth:
        return narrative

    result = narrative

    for val in sorted(set(ground_truth), reverse=True):
        pattern = re.compile(
            r'(?:(?:Rs\.?|INR|₹|\$)\s*)?(\b\d[\d,]*\.?\d*\b)',
            re.IGNORECASE
        )

        def replace_corrupted(match):
            matched_str = match.group(0)
            num_part = match.group(1).replace(",", "")
            try:
                num_val = float(num_part)
            except ValueError:
                return matched_str

            if num_val > 0:
                ratio = num_val / val
                # Check for 10x lower, 10x higher, or near-equality (rounding/formatting error)
                if (0.09 <= ratio <= 0.11) or (9.9 <= ratio <= 10.1) or (0.99 <= ratio <= 1.01):
                    prefix = "Rs. " if "rs" in matched_str.lower() else ("₹" if "₹" in matched_str else "₹")
                    return f"{prefix}{val:,.2f}"
            return matched_str

        result = pattern.sub(replace_corrupted, result)

    return result

def _generate_narrative(
    checks: List[Dict[str, Any]],
    discrepancies: List[Dict[str, Any]],
    evidence: Dict[str, Any]
) -> str:
    """Call LLM to generate narrative. Priority: Ollama first -> OpenRouter -> raise for template fallback."""
    passed_count = sum(1 for c in checks if c.get("status") == "pass")
    total_count = len(checks)
    failed_checks = _sort_by_severity([c for c in checks if c.get("status") in ("fail", "warning")])

    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    bank = evidence.get("bank_statement") or {}

    inv_amt_str = f"₹{inv.get('total_amount'):,.2f}" if inv.get("total_amount") is not None else "N/A"
    po_amt_str = f"₹{po.get('total_amount'):,.2f}" if po.get("total_amount") is not None else "N/A"
    pay_amt_str = f"₹{bank.get('payment_amount'):,.2f}" if bank.get("payment_amount") is not None else "N/A"

    financial_summary = {
        "verified_invoice_total": inv_amt_str,
        "verified_po_total": po_amt_str,
        "verified_payment_amount": pay_amt_str,
        "payment_date": bank.get("payment_date", "N/A"),
        "bank_reference": bank.get("bank_reference", "N/A"),
    }

    checks_summary = {
        "total_checks": total_count,
        "passed_checks": passed_count,
        "failed_checks": [
            {
                "check": c.get("check_type"),
                "status": c.get("status"),
                "expected": c.get("expected"),
                "actual": c.get("actual"),
                "explanation": c.get("explanation"),
            }
            for c in failed_checks
        ] if failed_checks else "All checks passed successfully."
    }

    prompt = (
        "Verified Financial Ground Truth (USE THESE EXACT AMOUNTS):\n"
        + json.dumps(financial_summary, indent=2)
        + "\n\nAudit Evidence:\n"
        + json.dumps(evidence, indent=2)
        + "\n\nVerification Summary:\n"
        + json.dumps(checks_summary, indent=2)
        + (f"\n\nDiscrepancies:\n{json.dumps(discrepancies, indent=2)}" if discrepancies else "")
    )

    # ── 1. Call Ollama (local llama2:latest) ─────────────────────────────────
    if settings.OLLAMA_HOST:
        try:
            payload = {
                "model": settings.OLLAMA_MODEL or "llama2:latest",
                "prompt": f"{_NARRATIVE_SYSTEM}\n\n{prompt}",
                "stream": False,
                "options": {
                    "num_predict": 250,
                    "temperature": 0.2,
                },
            }
            with httpx.Client(timeout=httpx.Timeout(180.0, connect=3.0)) as client:
                res = client.post(f"{settings.OLLAMA_HOST}/api/generate", json=payload)
                if res.status_code == 200:
                    text = res.json().get("response", "").strip()
                    logger.info(f"[ReportAgent] Ollama raw response (first 200 chars): {text[:200]}")
                    cleaned = _clean_narrative_text(text)
                    if cleaned:
                        cleaned = _enforce_monetary_integrity(cleaned, evidence)
                        logger.info("[ReportAgent] Using Ollama LLM narrative")
                        return cleaned
                    else:
                        logger.warning("[ReportAgent] Ollama narrative empty after cleaning")
                else:
                    logger.warning(f"[ReportAgent] Ollama HTTP {res.status_code}: {res.text}")
        except Exception as exc:
            logger.warning(f"[ReportAgent] Ollama narrative error: {exc}")

    # ── 2. Fallback to OpenRouter if key is valid ──────────────────────
    api_key = settings.OPENROUTER_API_KEY or ""
    if api_key and not api_key.startswith("your_"):
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Audit Report Detailed Narrative",
            }
            payload = {
                "model": settings.OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": _NARRATIVE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 600,
            }
            with httpx.Client(timeout=25.0) as client:
                res = client.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    cleaned = _clean_narrative_text(text)
                    if cleaned:
                        cleaned = _enforce_monetary_integrity(cleaned, evidence)
                        logger.info("[ReportAgent] Using OpenRouter LLM narrative")
                        return cleaned
        except Exception as exc:
            logger.warning(f"[ReportAgent] OpenRouter narrative error: {exc}")

    raise RuntimeError("LLM narrative generation unavailable")

def _template_narrative(
    bundle_id: str,
    checks: List[Dict[str, Any]],
    discrepancies: List[Dict[str, Any]],
    evidence: Dict[str, Any],
) -> str:
    """Deterministic fallback narrative grounded in DB evidence when LLM is unavailable."""
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor") or "unknown vendor"

    inv_amt_val = inv.get("total_amount")
    inv_amt = f"₹{inv_amt_val:,.2f}" if inv_amt_val is not None else "N/A"
    po_amt_val = po.get("total_amount")
    po_amt = f"₹{po_amt_val:,.2f}" if po_amt_val is not None else "N/A"
    pay_amt_val = bank.get("payment_amount")
    pay_amt = f"₹{pay_amt_val:,.2f}" if pay_amt_val is not None else "N/A"

    lines = [
        f"Audit Summary for Bundle {bundle_id}",
        f"Vendor: {vendor}",
    ]
    if inv:
        lines.append(f"Invoice #{inv.get('invoice_number')} | Total Amount: {inv_amt} | Date: {inv.get('invoice_date', 'N/A')}")
    if po:
        lines.append(f"Purchase Order #{po.get('po_number')} | Total Amount: {po_amt}")
    if grn:
        lines.append(f"Goods Received Note #{grn.get('grn_number')} | Date: {grn.get('grn_date', 'N/A')}")

    if bank.get("payment_status") == "confirmed":
        lines.append(f"Payment Status: Confirmed on {bank.get('payment_date')} (Ref: {bank.get('bank_reference')}, Amount: {pay_amt})")
    else:
        lines.append(f"Payment Status: {bank.get('payment_status', 'No payment confirmation found')}")

    lines.append("")

    failed = [c for c in checks if c.get("status") in ("fail", "warning")]
    if discrepancies:
        lines.append("Discrepancies Identified:")
        for d in _sort_by_severity(discrepancies):
            lines.append(
                f"  - [{d.get('severity', 'UNKNOWN').upper()}] {d.get('category', '')}: {d.get('description', '')}. "
                f"Recommended Action: {d.get('recommended_action', '')}"
            )
        lines.append("")

    if failed:
        lines.append("Failed/Warning Verification Checks:")
        for c in _sort_by_severity(failed):
            lines.append(
                f"  - {c.get('check_type')}: expected={c.get('expected')}, actual={c.get('actual')}. "
                f"{c.get('explanation', '')}"
            )
    else:
        lines.append("All 4-way match verification checks passed successfully.")

    return "\n".join(lines)

def report_summary_node(state: BundleState) -> Dict[str, Any]:
    """LangGraph node - summary report for clean or warning-only bundles."""
    bundle_id = state.get("bundle_id")
    start = time.time()
    logger.info(f"[ReportAgent:summary] Generating summary report for bundle {bundle_id}")

    checks = state.get("verification_checks") or []
    discrepancies = state.get("discrepancies") or []
    passed_count = sum(1 for c in checks if c.get("status") == "pass")
    total_count = len(checks)
    failed_checks = _sort_by_severity([c for c in checks if c.get("status") in ("fail", "warning")])

    db = SessionLocal()
    evidence = _get_bundle_evidence(db, bundle_id)

    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor") or "Vendor"

    inv_num = inv.get("invoice_number", "N/A")
    inv_amt = f"₹{inv.get('total_amount'):,.2f}" if inv.get('total_amount') is not None else "N/A"
    po_num = po.get("po_number", "N/A")

    pay_status_str = ""
    if bank.get("payment_status") == "confirmed":
        pay_amt_formatted = f"₹{bank.get('payment_amount'):,.2f}" if bank.get('payment_amount') is not None else inv_amt
        pay_status_str = f"Payment of {pay_amt_formatted} was confirmed on {bank.get('payment_date')} (Bank Ref: {bank.get('bank_reference')})."
    else:
        pay_status_str = "No matching bank statement payment record was found."

    # Template exec summary (always built, used as fallback)
    template_summary = (
        f"Audit bundle for Invoice #{inv_num} (Vendor: '{vendor}', Amount: {inv_amt}, PO #{po_num}) "
        f"passed 4-way match verification with {passed_count}/{total_count} checks passed. "
        f"{pay_status_str}"
    )

    # Try LLM narrative for a richer, natural-language summary
    narrative_source = "template"
    try:
        exec_summary = _generate_narrative(checks, discrepancies, evidence)
        narrative_source = "llm"
        logger.info("[ReportAgent:summary] Using LLM narrative for summary report")
    except Exception:
        exec_summary = template_summary
        logger.info("[ReportAgent:summary] LLM unavailable - using template summary")

    exec_summary = _enforce_monetary_integrity(exec_summary, evidence)

    report_json = {
        "report_type": "summary",
        "bundle_id": bundle_id,
        "verdict": state.get("verdict", "clean"),
        "severity": state.get("severity"),
        "risk_score": state.get("risk_score", 0.0),
        "checks_passed": passed_count,
        "checks_total": total_count,
        "verification_checks": checks,
        "failed_checks": failed_checks,
        "discrepancies_count": len(failed_checks),
        "discrepancies": _sort_by_severity(discrepancies),
        "evidence": evidence,
        "executive_summary": exec_summary,
        "note": exec_summary,
        "narrative_source": narrative_source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    report_id = None
    try:
        report_id = _persist_report(db, state.get("verification_run_id"), report_json)
        latency_ms = int((time.time() - start) * 1000)
        db.add(
            AgentExecutionLog(
                bundle_id=bundle_id,
                agent_name="report_agent_summary",
                input_snapshot={"bundle_id": bundle_id, "verdict": state.get("verdict")},
                output_snapshot={"report_id": report_id, "report_type": "summary"},
                latency_ms=latency_ms,
                status="success",
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning(f"[ReportAgent:summary] DB error: {exc}")
    finally:
        db.close()

    return {"report": report_json}

def report_detailed_node(state: BundleState) -> Dict[str, Any]:
    """LangGraph node - detailed report for anomaly / critical bundles."""
    bundle_id = state.get("bundle_id")
    start = time.time()
    logger.info(f"[ReportAgent:detailed] Generating detailed report for bundle {bundle_id}")

    checks = state.get("verification_checks") or []
    discrepancies = state.get("discrepancies") or []

    db = SessionLocal()
    evidence = _get_bundle_evidence(db, bundle_id)

    # Generate narrative
    try:
        narrative = _generate_narrative(checks, discrepancies, evidence)
        narrative_source = "llm"
    except Exception:
        narrative = _template_narrative(bundle_id, checks, discrepancies, evidence)
        narrative_source = "template_fallback"
        logger.info(f"[ReportAgent:detailed] Using grounded template fallback for bundle {bundle_id}")

    narrative = _enforce_monetary_integrity(narrative, evidence)

    failed_checks = _sort_by_severity(
        [c for c in checks if c.get("status") in ("fail", "warning")]
    )

    inv = evidence.get("invoice") or {}
    inv_num = inv.get("invoice_number", "N/A")
    vendor = evidence.get("vendor") or "Vendor"
    inv_amt = f"₹{inv.get('total_amount'):,.2f}" if inv.get('total_amount') is not None else "N/A"

    exec_summary = (
        f"Audit bundle for Invoice #{inv_num} (Vendor: '{vendor}', Amount: {inv_amt}) "
        f"was flagged with verdict '{state.get('verdict')}' ({state.get('severity')} severity) "
        f"due to {len(failed_checks)} failed check(s) and {len(discrepancies)} discrepancy(ies)."
    )

    report_json = {
        "report_type": "detailed",
        "bundle_id": bundle_id,
        "verdict": state.get("verdict", "anomaly"),
        "severity": state.get("severity"),
        "risk_score": state.get("risk_score", 0.0),
        "narrative": narrative,
        "executive_summary": narrative,
        "narrative_source": narrative_source,
        "evidence": evidence,
        "failed_checks": failed_checks,
        "discrepancies": _sort_by_severity(discrepancies),
        "discrepancies_count": len(failed_checks),
        "checks_total": len(checks),
        "checks_passed": sum(1 for c in checks if c.get("status") == "pass"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    report_id = None
    try:
        report_id = _persist_report(db, state.get("verification_run_id"), report_json)
        latency_ms = int((time.time() - start) * 1000)
        db.add(
            AgentExecutionLog(
                bundle_id=bundle_id,
                agent_name="report_agent_detailed",
                input_snapshot={
                    "bundle_id": bundle_id,
                    "verdict": state.get("verdict"),
                    "severity": state.get("severity"),
                },
                output_snapshot={
                    "report_id": report_id,
                    "report_type": "detailed",
                    "narrative_source": narrative_source,
                },
                latency_ms=latency_ms,
                status="success",
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning(f"[ReportAgent:detailed] DB error: {exc}")
    finally:
        db.close()

    return {"report": report_json}

def report_not_found_node(state: BundleState) -> Dict[str, Any]:
    """LangGraph node - returned when bundle_id is missing, invalid, or verification failed."""
    bundle_id = state.get("bundle_id")
    errors = state.get("errors") or []
    logger.warning(f"[ReportAgent:not_found] bundle_id={bundle_id}, errors={errors}")

    error_msg = errors[0] if errors else "Bundle not found or verification could not be completed."

    report_json = {
        "report_type": "not_found",
        "bundle_id": bundle_id,
        "verdict": "error",
        "severity": "critical",
        "risk_score": 0.0,
        "checks_passed": 0,
        "checks_total": 0,
        "discrepancies_count": 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": error_msg,
        "executive_summary": (
            f"Verification could not be completed. {error_msg} "
            "Please check the bundle ID or transaction reference and try again."
        ),
        "recommended_next_steps": (
            "Verify the bundle ID or PO/invoice number is correct and has been uploaded. "
            "If the document was recently uploaded, wait a moment and retry."
        ),
    }

    return {"report": report_json, "errors": errors}
