"""
QueryAgent - backend/app/agents/query_agent.py
----------------------------------------------
QA Agent for multi-agent evidence system (TASK 5).

Answers user questions strictly using the retrieved evidence_table
and deterministic verification results.
- Authoritative Source of Truth: Deterministic Verification Engine.
- LLM synthesizes natural-language explanations without inventing facts, changing verdicts, or speculating.
- Returns standardized response contract including deduplicated findings and locked source documents.
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.agents.llm_rules import GROUNDING_RULES
from app.agents.search_agent import _fetch_bundle_source_documents
from app.agents.state import BundleState
from app.core.config import settings
from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.models import (
    AgentExecutionLog, AuditBundle, BankStatement, BankTransaction,
    Discrepancy, Document, GRN, GRNLineItem, Invoice, InvoiceLineItem,
    PurchaseOrder, POLineItem, Vendor, VerificationCheck, VerificationRun,
)


def _clean_answer_text(raw_text: str) -> str:
    """Strip thinking process or preambles from response text using tag extraction with fallback."""
    if not raw_text:
        return ""
    text = raw_text.strip()

    tag_match = re.search(r"<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>", text, re.DOTALL | re.IGNORECASE)
    if tag_match:
        text = tag_match.group(1).strip()
    else:
        # Only apply heuristic stripping when the text is CLEARLY dominated by thinking-process boilerplate.
        thinking_indicators = [
            "thinking process", "analyze user request", "examine evidence table",
            "check grounding rules", "<think>"
        ]
        if any(k in text.lower() for k in thinking_indicators):
            # Remove any <think>...</think> blocks
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
            parts = text.split("\n\n")
            non_thinking = [
                p for p in parts
                if not re.match(r"^\d+\.\s*\*\*", p.strip()) and
                   not any(k in p.lower() for k in thinking_indicators)
            ]
            if non_thinking and len(non_thinking) >= len(parts) // 2:
                text = "\n\n".join(non_thinking).strip()

    text = re.sub(r"^```(?:markdown|text)?\n?", "", text, flags=re.I)
    text = re.sub(r"\n?```$", "", text, flags=re.I)
    return text.strip()


def _filter_evidence_for_prompt(user_query: str, evidence: dict, plan: Optional[dict] = None) -> dict:
    """Filter evidence_table to present clean, relevant document data to the LLM."""
    req_docs = plan.get("required_documents") if plan else None
    if isinstance(req_docs, list) and len(req_docs) > 0:
        req_set = {str(d).lower().strip() for d in req_docs}
    else:
        req_set = {"invoice", "purchase_order", "grn", "bank_statement"}

    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor_name")

    filtered = {}
    if vendor:
        filtered["vendor_name"] = vendor

    if "invoice" in req_set and inv:
        doc_inv = {"invoice_number": inv.get("invoice_number")}
        for f in ("subtotal", "tax_amount", "total_amount", "invoice_date", "due_date", "purchase_order", "po_number", "vendor_name"):
            if inv.get(f) is not None:
                doc_inv[f] = inv.get(f)
        if inv.get("line_items"):
            doc_inv["line_items"] = inv.get("line_items")
        filtered["invoice"] = doc_inv

    if "purchase_order" in req_set and po:
        doc_po = {"po_number": po.get("po_number")}
        for f in ("subtotal", "tax_amount", "total_amount", "po_date", "vendor_name"):
            if po.get(f) is not None:
                doc_po[f] = po.get(f)
        if po.get("line_items"):
            doc_po["line_items"] = po.get("line_items")
        filtered["purchase_order"] = doc_po

    if "grn" in req_set and grn:
        doc_grn = {"grn_number": grn.get("grn_number")}
        for f in ("grn_date", "delivery_note_number", "received_condition", "total_amount", "vendor_name"):
            if grn.get(f) is not None:
                doc_grn[f] = grn.get(f)
        if grn.get("line_items"):
            doc_grn["line_items"] = grn.get("line_items")
        filtered["grn"] = doc_grn

    if "bank_statement" in req_set and bank:
        doc_bank = {}
        if bank.get("account_number"):
            doc_bank["account_number"] = bank.get("account_number")
        if bank.get("payment_status"):
            doc_bank["payment_status"] = bank.get("payment_status")
        if bank.get("transactions"):
            doc_bank["transactions"] = bank.get("transactions")[:5]
        filtered["bank_statement"] = doc_bank

    return filtered if filtered else evidence


def _format_amount(val) -> str:
    if val is None or val == "":
        return "N/A"
    try:
        f = float(str(val).replace("₹", "").replace(",", "").replace("Rs.", "").strip())
        if f.is_integer():
            return f"₹{int(f):,}"
        return f"₹{f:,.2f}"
    except Exception:
        return f"₹{val}"


_CHECK_TITLES = {
    "po_invoice_total_match": "PO ↔ Invoice Amount Match",
    "po_invoice_ref_match": "PO ↔ Invoice Reference Match",
    "po_invoice_vendor_match": "Vendor Match (PO ↔ Invoice)",
    "po_grn_amount_match": "PO ↔ GRN Amount Match (Pre-Tax)",
    "grn_qty_match": "PO ↔ GRN Quantity Match",
    "grn_qty_short_shipment": "Short Shipment (GRN Qty < PO Qty)",
    "grn_qty_over_delivery": "Over Delivery (GRN Qty > PO Qty)",
    "grn_qty_zero_received": "Zero Quantity Received",
    "invoice_grn_amount_match": "Invoice ↔ GRN Amount Match",
    "tax_rate_consistency": "Tax Rate Consistency",
    "invoice_arithmetic_check": "Invoice Internal Arithmetic",
    "payment_amount_match": "Invoice ↔ Bank Debit Amount Match",
    "payment_before_invoice_date": "Payment Date Chronology (Invoice)",
    "payment_before_grn_date": "Payment Date Chronology (GRN)",
    "payment_matched_to_invoice": "Bank Payment Narration Match",
    "doc_completeness_purchase_order": "Document Completeness (PO)",
    "doc_completeness_invoice": "Document Completeness (Invoice)",
    "doc_completeness_grn": "Document Completeness (GRN)",
    "doc_completeness_bank_statement": "Document Completeness (Bank Statement)",
}


def _format_check_block(c: dict, evidence: dict) -> str:
    status = (c.get("status") or "").lower()
    check_type = c.get("check_type") or c.get("check_name") or "Check"
    title = _CHECK_TITLES.get(check_type, check_type.replace("_", " ").title())

    if status == "pass":
        symbol = "✓"
        res_str = "PASS"
    elif status == "fail":
        symbol = "✕"
        res_str = "FAIL"
    elif status == "warning":
        symbol = "⚠"
        res_str = "WARNING"
    else:
        symbol = "ℹ"
        res_str = status.upper()

    lines = [f"{symbol} {title}"]

    expected = c.get("expected")
    actual = c.get("actual")
    variance = c.get("variance")

    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}

    if check_type == "po_invoice_total_match":
        inv_tot = _format_amount(inv.get("total_amount") or actual)
        po_tot = _format_amount(po.get("total_amount") or expected)
        lines.append(f"PO: {po_tot}")
        lines.append(f"Invoice: {inv_tot}")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {_format_amount(variance)}")
    elif check_type == "po_invoice_ref_match":
        lines.append(f"PO: {po.get('po_number') or expected or 'N/A'}")
        lines.append(f"Invoice PO Ref: {inv.get('po_number') or inv.get('purchase_order') or actual or 'N/A'}")
    elif check_type == "po_invoice_vendor_match":
        po_vendor = po.get("vendor_name") or evidence.get("vendor_name") or expected or "N/A"
        inv_vendor = inv.get("vendor_name") or evidence.get("vendor_name") or actual or "N/A"
        lines.append(f"PO: {po_vendor}")
        lines.append(f"Invoice: {inv_vendor}")
    elif check_type in ("grn_qty_match", "grn_qty_short_shipment", "grn_qty_over_delivery", "grn_qty_zero_received"):
        po_qty = expected if expected is not None else "N/A"
        grn_qty = actual if actual is not None else "N/A"
        lines.append(f"PO: {po_qty} units")
        lines.append(f"GRN: {grn_qty} units")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {variance} units")
    elif check_type == "po_grn_amount_match":
        po_sub = _format_amount(po.get("subtotal") or expected)
        grn_tot = _format_amount(grn.get("total_amount") or actual)
        lines.append(f"PO (Pre-Tax): {po_sub}")
        lines.append(f"GRN: {grn_tot}")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {_format_amount(variance)}")
    elif check_type == "invoice_grn_amount_match":
        inv_sub = _format_amount(inv.get("subtotal") or expected)
        grn_tot = _format_amount(grn.get("total_amount") or actual)
        lines.append(f"Invoice (Pre-Tax): {inv_sub}")
        lines.append(f"GRN: {grn_tot}")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {_format_amount(variance)}")
    elif check_type == "tax_rate_consistency":
        lines.append(f"PO: {expected}%")
        lines.append(f"Invoice: {actual}%")
    elif check_type == "invoice_arithmetic_check":
        lines.append(f"Subtotal + Tax: {_format_amount(expected)}")
        lines.append(f"Invoice Stated Total: {_format_amount(actual)}")
    elif expected is not None or actual is not None:
        if expected is not None:
            lines.append(f"Expected: {expected}")
        if actual is not None:
            lines.append(f"Actual: {actual}")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {variance}")

    if c.get("explanation"):
        lines.append(f"Detail: {c.get('explanation')}")

    lines.append(f"Result: {res_str}")
    return "\n".join(lines)


def _get_quantity_summary(evidence: dict) -> str:
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    po_lines = po.get("line_items") or []
    grn_lines = grn.get("line_items") or []

    po_qty = sum(float(l.get("qty", 0) or 0) for l in po_lines) if po_lines else None
    grn_qty = sum(float(l.get("qty_received", 0) or 0) for l in grn_lines) if grn_lines else None

    if po_qty is not None and grn_qty is not None:
        po_str = f"{int(po_qty) if po_qty.is_integer() else po_qty} units"
        grn_str = f"{int(grn_qty) if grn_qty.is_integer() else grn_qty} units"
        if po_qty == grn_qty:
            return f"{po_str} (Matched)"
        diff = abs(po_qty - grn_qty)
        diff_str = f"{int(diff) if diff.is_integer() else diff} units"
        return f"PO: {po_str} | GRN: {grn_str} (Difference: {diff_str})"
    elif po_qty is not None:
        return f"{int(po_qty) if po_qty.is_integer() else po_qty} units"
    elif grn_qty is not None:
        return f"{int(grn_qty) if grn_qty.is_integer() else grn_qty} units"
    return "N/A"


def _determine_overall_status(verdict: Optional[str], checks: List[dict], risk_score: float) -> str:
    v = (verdict or "").lower()
    if v == "clean" or (not any(c.get("status") in ("fail", "warning") for c in checks) and risk_score == 0):
        return "VERIFIED"
    if v == "critical" or any(c.get("status") == "fail" for c in checks) or risk_score >= 20:
        return "FAILED"
    if any(c.get("status") == "warning" for c in checks) or risk_score > 0:
        return "REVIEW REQUIRED"
    return "VERIFIED"


def _filter_checks_for_query(checks: List[dict], user_query: str) -> List[dict]:
    """
    Return checks prioritized for the specific user question.
    """
    q = (user_query or "").lower()
    if not checks:
        return []

    # Amount questions
    if any(k in q for k in ["amount", "total", "subtotal", "tax", "arithmetic", "price", "mismatch"]):
        amount_types = {
            "po_invoice_total_match", "po_grn_amount_match", "invoice_grn_amount_match",
            "invoice_arithmetic_check", "tax_rate_consistency", "payment_amount_match"
        }
        prioritized = [c for c in checks if (c.get("check_type") or c.get("check_name")) in amount_types]
        if prioritized:
            return prioritized

    # GRN / quantity questions
    if any(k in q for k in ["grn", "quantity", "qty", "deliver", "received", "goods receipt", "short shipment", "over delivery"]):
        grn_types = {
            "grn_qty_match", "grn_qty_short_shipment", "grn_qty_over_delivery", "grn_qty_zero_received",
            "po_grn_amount_match", "invoice_grn_amount_match", "doc_completeness_grn"
        }
        prioritized = [c for c in checks if (c.get("check_type") or c.get("check_name")) in grn_types]
        if prioritized:
            return prioritized

    # Payment / Bank statement questions
    if any(k in q for k in ["paid", "payment", "bank", "debit", "transaction"]):
        pay_types = {
            "payment_amount_match", "payment_before_invoice_date", "payment_before_grn_date",
            "payment_matched_to_invoice", "doc_completeness_bank_statement"
        }
        prioritized = [c for c in checks if (c.get("check_type") or c.get("check_name")) in pay_types]
        if prioritized:
            return prioritized

    # Vendor questions
    if any(k in q for k in ["vendor", "supplier", "seller"]):
        vendor_types = {"po_invoice_vendor_match"}
        prioritized = [c for c in checks if (c.get("check_type") or c.get("check_name")) in vendor_types]
        if prioritized:
            return prioritized

    return [c for c in checks if (c.get("status") or "").lower() != "not_applicable"]


def _format_deterministic_verification_response(evidence: dict, verification_info: dict, bundle_id: Optional[str] = None, user_query: str = "") -> str:
    """Generate comprehensive structured Markdown verification response grounded purely in deterministic results."""
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name") or "N/A"

    checks = verification_info.get("checks") or []
    discrepancies = verification_info.get("discrepancies") or []
    verdict = verification_info.get("verdict")
    risk_score = float(verification_info.get("risk_score") or 0.0)

    overall_status = verification_info.get("overall_status") or _determine_overall_status(verdict, checks, risk_score)

    passed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "pass")
    failed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "fail")
    warning_count = sum(1 for c in checks if (c.get("status") or "").lower() == "warning")
    disc_count = len(discrepancies) if discrepancies else (failed_count + warning_count)

    po_num = po.get("po_number") or inv.get("po_number") or inv.get("purchase_order") or "N/A"
    inv_num = inv.get("invoice_number") or "N/A"
    grn_num = grn.get("grn_number") or "N/A"

    inv_total_str = _format_amount(inv.get("total_amount"))
    po_total_str = _format_amount(po.get("total_amount") or po.get("subtotal"))
    grn_total_str = _format_amount(grn.get("total_amount"))
    qty_str = _get_quantity_summary(evidence)

    # Filter checks
    relevant_checks = _filter_checks_for_query(checks, user_query)
    if not relevant_checks:
        relevant_checks = [c for c in checks if (c.get("status") or "").lower() != "not_applicable"]

    checks_blocks = [_format_check_block(c, evidence) for c in relevant_checks]
    checks_str = "\n\n".join(checks_blocks) if checks_blocks else "No relevant verification checks recorded."

    # Findings / Exceptions with deduplication
    findings = []
    seen_exps = set()
    for c in checks:
        st = (c.get("status") or "").lower()
        if st in ("fail", "warning"):
            exp = c.get("explanation") or f"Check {c.get('check_name')} resulted in {st}."
            if exp not in seen_exps:
                seen_exps.add(exp)
                sev = (c.get("severity") or "").upper()
                sev_str = f" [{sev}]" if sev else ""
                findings.append(f"- {exp}{sev_str}")

    for d in discrepancies:
        desc = d.get("description")
        if desc and desc not in seen_exps and not any(desc in f for f in findings):
            seen_exps.add(desc)
            rec = d.get("recommended_action")
            rec_str = f" Action: {rec}" if rec else ""
            findings.append(f"- {desc}{rec_str}")

    findings_str = "\n".join(findings) if findings else "No discrepancies or exceptions found. All deterministic checks passed."

    return f"""## Deterministic Verification Findings (SOURCE OF TRUTH)
Overall Status: {overall_status}
Verdict: {verdict or overall_status}
Risk Score: {int(risk_score)}/100
Invoice: {inv_num} (Total: {inv_total_str})
Purchase Order: {po_num} (Total: {po_total_str})
GRN: {grn_num} (Total: {grn_total_str})
Vendor: {vendor}
Quantity: {qty_str}
Checks Passed: {passed_count}, Checks Failed: {failed_count}, Warnings: {warning_count}

### Relevant Checks:
{checks_str}

### Discrepancies & Findings:
{findings_str}"""


_VERIFICATION_SYSTEM_PROMPT = """You are an enterprise Audit Intelligence Assistant.
The deterministic verification engine has executed all 3-way and 4-way matching rules against the source documents and is the AUTHORITATIVE SOLE SOURCE OF TRUTH.

Your task is to write a concise, professional natural-language audit explanation paragraph that directly answers the user's specific question (e.g. whether documents match, why a transaction was flagged, total amounts, or payment status).

CRITICAL GROUNDING & ACCURACY RULES:
1. Direct Answer: Answer the user's question directly in the opening sentence. State what was verified, exact document numbers (Invoice #, PO #, GRN #), exact amounts or quantities, and the verdict clearly.
2. Grounding: Answer ONLY from the supplied deterministic verification results and evidence table. Do NOT invent, assume, or alter any numbers, dates, or facts.
3. Zero Speculation: Do NOT use speculation words ("fraud", "unauthorized", "backdated", "approved") unless explicitly stated in the deterministic findings. If evidence is missing or ambiguous, state clearly that it cannot be determined from the available documents.
4. No Redundant Headers: Do NOT output markdown section headers (like "## Verification Result" or "### Summary"). The UI renders structured tables and badges automatically below your response.
5. Return ONLY the final natural-language explanation paragraph."""


def _build_template_answer(user_query: str, evidence: dict, plan: Optional[dict] = None) -> str:
    """Deterministic fallback QA answer grounded strictly in retrieved evidence when LLM is unavailable."""
    q_lower = (user_query or "").lower()
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name") or "Vendor"

    if any(k in q_lower for k in ["total", "amount", "subtotal", "tax", "price"]) and inv:
        tot = inv.get("total_amount")
        num = inv.get("invoice_number", "N/A")
        if tot is not None:
            return f"Invoice {num} total amount is {_format_amount(tot)} (Vendor: {vendor})."
    if any(k in q_lower for k in ["quantity", "qty", "received", "grn", "units"]) and grn:
        lines = grn.get("line_items") or []
        if lines:
            line_str = ", ".join([f"{l.get('description', 'Item')}: received {l.get('qty_received', 0)}" for l in lines])
            return f"GRN {grn.get('grn_number', 'N/A')} received items: {line_str}."
    if any(k in q_lower for k in ["item", "items", "ordered", "po", "purchase order"]) and po:
        lines = po.get("line_items") or []
        if lines:
            line_str = ", ".join([f"{l.get('description', 'Item')} (Qty: {l.get('qty', 0)})" for l in lines])
            return f"PO {po.get('po_number', 'N/A')} ordered items: {line_str}."
    if any(k in q_lower for k in ["paid", "payment", "bank"]) and bank:
        status = bank.get("payment_status", "recorded")
        txns = bank.get("transactions") or []
        if txns:
            t0 = txns[0]
            amt = _format_amount(t0.get("amount") or t0.get("debit_amount"))
            return f"Bank record indicates payment of {amt} with status: {status}."
        return f"Payment status: {status}."
    return "The requested information is not available in the retrieved evidence."


def _build_result_metadata(evidence: dict, bundle_id: Optional[str]) -> dict:
    """Build structured result metadata for frontend display cards."""
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name")

    found = bool(inv or po or grn or bank)
    status = "VERIFIED" if found else "NOT FOUND"
    return {
        "found": found,
        "status": status,
        "ambiguous": False,
        "bundle_id": bundle_id,
        "vendor_name": vendor,
        "invoice_number": inv.get("invoice_number"),
        "po_number": po.get("po_number"),
        "grn_number": grn.get("grn_number"),
        "total_amount": inv.get("total_amount") or po.get("total_amount"),
    }


def _build_intent_system_prompt(intent: str = "") -> str:
    return """You are an enterprise Audit Intelligence Assistant.
Answer the user's exact question directly, concisely, and professionally using only the supplied evidence.
The supplied evidence contains the verified, matching records retrieved for the query.
Do not invent facts, numbers, or dates.
State specific document numbers, values, and vendor names directly in the opening sentence.
Do not claim that the document is missing or not mentioned when its details are present in the evidence table.
Provide a clear, natural-language explanation in 1-2 concise paragraphs.
Do not output markdown section headers or raw data dumps.
Return only the final answer."""


def _is_verification_query(user_query: str, plan: Optional[dict], verification_info: Optional[dict]) -> bool:
    if plan:
        if plan.get("verification_required") is True:
            return True
        if plan.get("intent") in ("comparison", "verification", "full_audit"):
            return True
        if plan.get("intent") in ("lookup", "field_lookup", "payment_lookup") and plan.get("verification_required") is False:
            return False
    q = (user_query or "").lower()
    verif_keywords = ["verify", "verification", "3-way", "4-way", "three-way", "four-way", "compare"]
    if any(k in q for k in verif_keywords) and verification_info and (verification_info.get("checks") or verification_info.get("verdict")):
        return True
    return False


def _synthesize_answer(user_query: str, evidence: dict, plan: Optional[dict] = None, verification_info: Optional[dict] = None, bundle_id: Optional[str] = None) -> str:
    """Synthesize plain-English QA answer via local Ollama strictly grounded in filtered evidence_table & verification results."""
    is_verif = _is_verification_query(user_query, plan, verification_info)

    # If verification query, prepare deterministic report as source of truth
    deterministic_verif_report = ""
    if is_verif and verification_info:
        deterministic_verif_report = _format_deterministic_verification_response(evidence, verification_info, bundle_id, user_query)

    # Filter evidence to send only relevant documents
    filtered_evidence = _filter_evidence_for_prompt(user_query, evidence, plan)
    logger.info(f"[QueryAgent] Evidence sent to LLM: {json.dumps(filtered_evidence)}")
    evidence_json = json.dumps(filtered_evidence, indent=2)

    if is_verif and deterministic_verif_report:
        system_prompt = _VERIFICATION_SYSTEM_PROMPT
        user_prompt = (
            f"User question: {json.dumps(user_query)}\n\n"
            f"Authoritative Deterministic Verification Results (SOURCE OF TRUTH):\n{deterministic_verif_report}\n\n"
            f"Evidence Documents Table:\n{evidence_json}"
        )
        max_tokens = 600
    else:
        intent = plan.get("intent", "lookup") if plan else "lookup"
        system_prompt = _build_intent_system_prompt(intent)
        user_prompt = f"User question: {json.dumps(user_query)}\n\nEvidence Table:\n{evidence_json}"
        max_tokens = 300

    # ── 1. Call Ollama (local qwen2.5:3b) ───────────────────────────────────
    if settings.OLLAMA_HOST:
        try:
            ollama_model = settings.OLLAMA_MODEL or "qwen2.5:3b"
            payload = {
                "model": ollama_model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.1,
                },
            }
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                res = client.post(f"{settings.OLLAMA_HOST}/api/generate", json=payload)
                if res.status_code == 200:
                    raw = res.json().get("response", "").strip()
                    logger.info(f"[QueryAgent] Ollama ({ollama_model}) raw response: {raw[:300]}")
                    cleaned = _clean_answer_text(raw)
                    REFUSAL_PATTERNS = [
                        "not available in the retrieved evidence",
                        "i cannot answer",
                        "i don't have",
                        "information is not available",
                        "no information provided",
                        "cannot determine",
                    ]
                    is_refusal = any(p in cleaned.lower() for p in REFUSAL_PATTERNS)
                    if cleaned and not is_refusal:
                        logger.info("[QueryAgent] Using Ollama LLM answer")
                        return cleaned
        except Exception as exc:
            logger.warning(f"[QueryAgent] Ollama synthesis error: {exc}")

    # ── 2. Fallback to OpenRouter if key is set and valid ─────────────────
    api_key = settings.OPENROUTER_API_KEY or ""
    if api_key and not api_key.startswith("your_"):
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Audit QA Answer",
            }
            payload = {
                "model": settings.OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.2,
            }
            with httpx.Client(timeout=30.0) as client:
                res = client.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    resp_json = res.json()
                    choices = resp_json.get("choices", [])
                    if choices:
                        msg = choices[0].get("message") or {}
                        raw = (msg.get("content") or "").strip()
                        if raw:
                            cleaned = _clean_answer_text(raw)
                            if cleaned:
                                logger.info("[QueryAgent] Using OpenRouter LLM answer")
                                return cleaned
        except Exception as exc:
            logger.warning(f"[QueryAgent] OpenRouter synthesis error: {exc}")

    # ── 3. Deterministic Source-of-Truth Fallback ───────────────────────────
    if is_verif and deterministic_verif_report:
        logger.info("[QueryAgent] Returning deterministic fallback summary")
        inv = evidence.get("invoice") or {}
        po = evidence.get("purchase_order") or {}
        grn = evidence.get("grn") or {}
        st = verification_info.get("overall_status", "COMPLETED")
        return f"Deterministic Verification Status: {st}. Invoice {inv.get('invoice_number', 'N/A')}, PO {po.get('po_number', 'N/A')}, and GRN {grn.get('grn_number', 'N/A')} were analyzed against 3-way matching rules."

    logger.warning("[QueryAgent] LLM generation unavailable — returning deterministic template answer")
    template_facts = _build_template_answer(user_query, evidence, plan)
    if is_verif and verification_info and verification_info.get("verdict"):
        verdict_str = verification_info.get("verdict", "").upper()
        return f"Deterministic Verification Verdict: {verdict_str}\n\n{template_facts}"
    return template_facts


def _fetch_status_bundles(db, query_filters: Optional[dict] = None) -> List[dict]:
    """Fetch bundle status rows from DB for system status queries."""
    try:
        q = db.query(AuditBundle)
        if query_filters and "status" in query_filters:
            q = q.filter(AuditBundle.status == query_filters["status"])
        bundles = q.order_by(AuditBundle.created_at.desc()).limit(50).all()

        rows = []
        for b in bundles:
            vrun = (
                db.query(VerificationRun)
                .filter(VerificationRun.bundle_id == b.bundle_id)
                .order_by(VerificationRun.started_at.desc())
                .first()
            )
            failed_checks = []
            risk_score = 0.0
            overall_status = b.status or "unknown"
            verdict = "clean"

            if vrun:
                risk_score = float(vrun.overall_risk_score or 0)
                vrun_status = vrun.overall_status or ""
                if vrun_status in ("anomaly", "critical", "flagged"):
                    overall_status = "flagged"
                    verdict = "anomaly"
                elif vrun_status == "clean":
                    overall_status = "clean"
                    verdict = "clean"

                failed = (
                    db.query(VerificationCheck)
                    .filter(
                        VerificationCheck.run_id == vrun.run_id,
                        VerificationCheck.status == "fail",
                    )
                    .all()
                )
                failed_checks = [
                    {
                        "check_name": c.check_name,
                        "explanation": c.explanation,
                        "variance": str(c.variance) if c.variance is not None else None,
                    }
                    for c in failed
                ]

            rows.append({
                "bundle_id": str(b.bundle_id),
                "txn_reference": b.txn_reference,
                "status": overall_status,
                "overall_status": overall_status,
                "verdict": verdict,
                "risk_score": risk_score,
                "failed_checks": failed_checks,
            })
        return rows
    except Exception as exc:
        logger.warning(f"[QueryAgent] Status bundle fetch error: {exc}")
        return []


def _synthesize_status_answer(user_query: str, bundles_list: List[dict]) -> str:
    """Generate concise natural language summary for multi-bundle/status queries."""
    q_lower = (user_query or "").lower()
    total_bundles = len(bundles_list)
    flagged_bundles = [b for b in bundles_list if b.get("overall_status") == "flagged" or b.get("risk_score", 0) > 0 or b.get("failed_checks")]

    # If asking specifically about amount mismatches
    if "amount mismatch" in q_lower or "amount mismatches" in q_lower or "mismatch" in q_lower:
        amount_flagged = []
        for b in bundles_list:
            failed = b.get("failed_checks") or []
            amt_fails = [f for f in failed if any(k in (f.get("check_name") or "").lower() for k in ["amount", "total", "subtotal", "arithmetic", "tax"])]
            if amt_fails:
                amount_flagged.append((b, amt_fails))

        if amount_flagged:
            lines = [f"Found {len(amount_flagged)} bundle(s) with amount mismatches:"]
            for b, fails in amount_flagged:
                exp_list = "; ".join(f.get("explanation") or f.get("check_name") for f in fails)
                lines.append(f"- Transaction {b.get('txn_reference') or b.get('bundle_id')}: {exp_list}")
            return "\n".join(lines)
        else:
            return "No amount mismatches were found across the evaluated audit bundles."

    if "flagged" in q_lower or "high risk" in q_lower or "critical" in q_lower:
        if flagged_bundles:
            lines = [f"Found {len(flagged_bundles)} flagged audit bundle(s) requiring review:"]
            for b in flagged_bundles:
                fails = b.get("failed_checks") or []
                fail_summary = ", ".join(f.get("check_name") for f in fails[:3]) if fails else "Risk score elevated"
                lines.append(f"- Transaction {b.get('txn_reference') or b.get('bundle_id')} (Risk: {int(b.get('risk_score', 0))}/100): {fail_summary}")
            return "\n".join(lines)
        else:
            return "All audit bundles are currently clean with zero flagged discrepancies."

    return f"Found {total_bundles} audit bundle(s) in the system ({len(flagged_bundles)} flagged for audit review)."


def _is_status_query(user_query: str, retrieval_plan: Optional[dict], bundle_id: Optional[str]) -> bool:
    """
    Determine if this is a system-wide bundle status/cross-bundle query.
    """
    if bundle_id:
        return False
    q = (user_query or "").lower()
    status_keywords = [
        "all bundles", "flagged", "show bundles", "list bundles", "bundles are",
        "high risk", "critical", "which bundles", "how many bundles",
        "show all", "list all", "status", "overview", "all amount mismatches",
        "show me all", "all discrepancies"
    ]
    return any(k in q for k in status_keywords)


def _build_structured_verification_summary(
    evidence: dict,
    verification_info: dict,
    bundle_id: Optional[str] = None,
    llm_answer: Optional[str] = None,
    db = None,
    required_documents: Optional[List[str]] = None,
) -> Optional[dict]:
    if not verification_info or not verification_info.get("checks"):
        return None

    checks = verification_info.get("checks") or []
    discrepancies = verification_info.get("discrepancies") or []
    verdict = verification_info.get("verdict")
    risk_score = float(verification_info.get("risk_score") or 0.0)
    overall_status = verification_info.get("overall_status") or _determine_overall_status(verdict, checks, risk_score)

    passed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "pass")
    failed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "fail")
    warning_count = sum(1 for c in checks if (c.get("status") or "").lower() == "warning")
    disc_count = len(discrepancies) if discrepancies else (failed_count + warning_count)

    # Ensure canonical evidence has all documents for complete financial & match reporting
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}

    if db and bundle_id and (not inv or not po or not grn or not bank):
        try:
            from app.agents.search_agent import _fetch_bundle_evidence
            full_evidence = _fetch_bundle_evidence(db, bundle_id, {"required_documents": ["invoice", "purchase_order", "grn", "bank_statement"], "required_fields": "all"})
            if not inv and full_evidence.get("invoice"):
                inv = full_evidence["invoice"]
            if not po and full_evidence.get("purchase_order"):
                po = full_evidence["purchase_order"]
            if not grn and full_evidence.get("grn"):
                grn = full_evidence["grn"]
            if not bank and full_evidence.get("bank_statement"):
                bank = full_evidence["bank_statement"]
        except Exception as exc:
            logger.warning(f"[QueryAgent] Error filling canonical evidence in verification summary: {exc}")

    vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name") or "N/A"

    paid_amt = None
    inv_num = str(inv.get("invoice_number") or "").strip()
    if bank.get("transactions") and isinstance(bank.get("transactions"), list) and len(bank.get("transactions")) > 0:
        txns = bank.get("transactions")
        matched_txn = next(
            (t for t in txns if inv_num and (inv_num.lower() in (t.get("extracted_invoice_number") or "").lower() or inv_num.lower() in (t.get("description") or "").lower())),
            None
        )
        if not matched_txn:
            matched_txn = next((t for t in txns if (t.get("debit") or t.get("debit_amount") or 0) > 0), txns[0])
        if matched_txn:
            paid_amt = matched_txn.get("amount") or matched_txn.get("debit_amount") or matched_txn.get("debit") or matched_txn.get("credit_amount") or matched_txn.get("credit")
    elif bank.get("payment_amount"):
        paid_amt = bank.get("payment_amount")

    financials = {
        "po_total": po.get("total_amount") or po.get("subtotal"),
        "invoice_total": inv.get("total_amount"),
        "grn_total": grn.get("total_amount"),
        "paid_amount": paid_amt,
    }

    def _match_status(check_types: List[str]) -> Dict[str, str]:
        matched = [c for c in checks if (c.get("check_type") or c.get("check_name")) in check_types]
        if not matched:
            return {"status": "not_applicable", "detail": "Not evaluated"}
        if any(c.get("status") == "fail" for c in matched):
            f_chk = next(c for c in matched if c.get("status") == "fail")
            return {"status": "fail", "detail": f_chk.get("explanation", "Discrepancy detected")}
        if any(c.get("status") == "warning" for c in matched):
            w_chk = next(c for c in matched if c.get("status") == "warning")
            return {"status": "warning", "detail": w_chk.get("explanation", "Variance warning detected")}
        return {"status": "pass", "detail": "Match verified"}

    document_matches = [
        {"label": "PO ↔ Invoice", **_match_status(["po_invoice_total_match", "po_invoice_ref_match", "po_invoice_vendor_match", "tax_rate_consistency", "invoice_arithmetic_check"])},
        {"label": "PO ↔ GRN", **_match_status(["po_grn_amount_match", "grn_qty_match", "grn_qty_short_shipment", "grn_qty_over_delivery", "grn_qty_zero_received"])},
        {"label": "Invoice ↔ GRN", **_match_status(["invoice_grn_amount_match"])},
        {"label": "Invoice ↔ Bank", **_match_status(["payment_amount_match", "payment_before_invoice_date", "payment_before_grn_date", "payment_matched_to_invoice"])},
    ]

    # Deduplicated Findings
    findings_list = []
    seen_explanations = set()
    for c in checks:
        st = (c.get("status") or "").lower()
        if st in ("fail", "warning"):
            chk_title = _CHECK_TITLES.get(c.get("check_type") or c.get("check_name"), c.get("check_name", "Check"))
            exp = c.get("explanation") or f"{chk_title} resulted in {st}"
            if exp not in seen_explanations:
                seen_explanations.add(exp)
                findings_list.append({
                    "check_name": chk_title,
                    "status": st,
                    "severity": (c.get("severity") or "HIGH").upper(),
                    "explanation": exp,
                    "expected": c.get("expected"),
                    "actual": c.get("actual"),
                    "variance": c.get("variance")
                })

    for d in discrepancies:
        desc = d.get("description")
        if desc and desc not in seen_explanations and not any(f.get("explanation") == desc for f in findings_list):
            seen_explanations.add(desc)
            findings_list.append({
                "check_name": d.get("category", "Discrepancy").replace("_", " ").title(),
                "status": "fail" if d.get("severity") in ("critical", "high") else "warning",
                "severity": (d.get("severity") or "MEDIUM").upper(),
                "explanation": desc + (f" Action: {d.get('recommended_action')}" if d.get('recommended_action') else "")
            })

    if overall_status == "VERIFIED":
        conclusion = "The 3-way match between Invoice, Purchase Order, and GRN is fully verified and consistent with no discrepancies. The transaction is validated and approved for processing."
    elif overall_status == "FAILED":
        conclusion = "Verification failed due to discrepancies identified during deterministic multi-way matching. Payment should be held pending investigation and resolution of the noted exceptions."
    else:
        conclusion = "Verification completed with warnings. Manual audit review is recommended to reconcile the identified variances before final payment approval."

    # Fetch physical source documents strictly locked to bundle_id
    source_docs = []
    if db and bundle_id:
        try:
            source_docs = _fetch_bundle_source_documents(db, bundle_id, required_documents)
        except Exception as exc:
            logger.warning(f"[QueryAgent] Error fetching source documents for bundle {bundle_id}: {exc}")

    # Fallback to metadata labels if DB source docs empty
    if not source_docs:
        if inv.get("invoice_number"):
            source_docs.append({"label": f"Invoice {inv.get('invoice_number')}", "type": "invoice", "doc_type": "invoice", "date": inv.get("invoice_date")})
        if po.get("po_number"):
            source_docs.append({"label": f"PO {po.get('po_number')}", "type": "purchase_order", "doc_type": "purchase_order", "date": po.get("po_date")})
        if grn.get("grn_number"):
            source_docs.append({"label": f"GRN {grn.get('grn_number')}", "type": "grn", "doc_type": "grn", "date": grn.get("grn_date")})
        if bank.get("account_number") or bank.get("payment_status") or bank.get("transactions"):
            source_docs.append({"label": "Bank Statement" + (f" ({bank.get('account_number')})" if bank.get("account_number") else ""), "type": "bank_statement", "doc_type": "bank_statement", "date": None})

    formatted_checks = []
    for c in checks:
        st = (c.get("status") or "").lower()
        if st == "not_applicable":
            continue
        chk_type = c.get("check_type") or c.get("check_name") or "Check"
        title = _CHECK_TITLES.get(chk_type, chk_type.replace("_", " ").title())
        formatted_checks.append({
            "check_type": chk_type,
            "title": title,
            "status": st,
            "severity": c.get("severity"),
            "expected": c.get("expected"),
            "actual": c.get("actual"),
            "variance": c.get("variance"),
            "explanation": c.get("explanation"),
            "block_text": _format_check_block(c, evidence)
        })

    return {
        "overall_status": overall_status,
        "verdict": verdict or overall_status,
        "explanation": llm_answer or conclusion,
        "llm_answer": llm_answer,
        "risk_score": risk_score,
        "checks_passed": passed_count,
        "checks_failed": failed_count,
        "warnings_count": warning_count,
        "discrepancies_count": disc_count,
        "financials": financials,
        "document_matches": document_matches,
        "findings": findings_list,
        "conclusion": conclusion,
        "vendor_name": vendor,
        "invoice_number": inv.get("invoice_number"),
        "po_number": po.get("po_number"),
        "grn_number": grn.get("grn_number"),
        "source_documents": source_docs,
        "formatted_checks": formatted_checks,
    }


def query_node(state: BundleState) -> Dict[str, Any]:
    """LangGraph Node: QA Agent."""
    start = time.time()
    user_query = state.get("user_query") or ""
    bundle_id = state.get("bundle_id")
    evidence_table = state.get("evidence_table")
    retrieval_plan = state.get("retrieval_plan")
    query_filters = state.get("query_filters")

    logger.info(f"[QueryAgent] Answering query: '{user_query}' for bundle {bundle_id}")

    # ── CASE 0: No bundle resolved & not a status query — vendor/document not found ──
    if not bundle_id and not _is_status_query(user_query, retrieval_plan, bundle_id):
        db = SessionLocal()
        known_vendors = []
        try:
            vendors = db.query(Vendor).all()
            known_vendors = [v.name_normalized for v in vendors if v.name_normalized]
        except Exception:
            pass
        finally:
            db.close()

        vendor_list_str = ", ".join(known_vendors) if known_vendors else "(none found)"
        not_found_answer = (
            f"No matching vendor or document was found for your query. "
            f"Known vendors currently in the system: {vendor_list_str}. "
            f"Please verify the vendor name or provide a specific PO / Invoice number."
        )
        logger.warning(f"[QueryAgent] No bundle resolved for query: '{user_query}'.")

        report_output = {
            "query": user_query,
            "query_type": "field_lookup",
            "answer_type": "field_lookup",
            "bundle_id": None,
            "bundle": None,
            "answer": not_found_answer,
            "result": {"found": False, "status": "NOT FOUND", "ambiguous": False, "bundle_id": None},
            "evidence": {},
            "verification_checks": [],
            "source_documents": [],
            "retrieval_plan": retrieval_plan,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"report": report_output, "answer": not_found_answer}

    # ── CASE 1: System-wide bundle status / cross-bundle query ─────────────────
    if _is_status_query(user_query, retrieval_plan, bundle_id):
        logger.info("[QueryAgent] Detected system status / cross-bundle query")
        db = SessionLocal()
        try:
            bundles_list = _fetch_status_bundles(db, query_filters)
        finally:
            db.close()

        status_answer = _synthesize_status_answer(user_query, bundles_list)

        report_output = {
            "query": user_query,
            "query_type": "status_query",
            "answer_type": "status_query",
            "bundle_id": None,
            "bundle": None,
            "answer": status_answer,
            "bundles": bundles_list,
            "result_count": len(bundles_list),
            "filters_applied": query_filters or {},
            "retrieval_plan": retrieval_plan,
            "source_documents": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        db = SessionLocal()
        try:
            db.add(
                AgentExecutionLog(
                    bundle_id=None,
                    agent_name="query_agent",
                    input_snapshot={"user_query": user_query, "bundle_id": None},
                    output_snapshot={"answer": status_answer, "result_count": len(bundles_list)},
                    latency_ms=int((time.time() - start) * 1000),
                    status="success",
                )
            )
            db.commit()
        except Exception as exc:
            logger.warning(f"[QueryAgent] DB log error: {exc}")
        finally:
            db.close()

        return {"report": report_output, "answer": status_answer}

    # ── CASE 2: Specific query for a resolved bundle ──────────────────────────
    if not evidence_table and bundle_id:
        db = SessionLocal()
        try:
            from app.agents.search_agent import _fetch_bundle_evidence
            evidence_table = _fetch_bundle_evidence(db, bundle_id, retrieval_plan)
        except Exception as exc:
            logger.warning(f"[QueryAgent] Error fetching evidence table: {exc}")
        finally:
            db.close()

    evidence_table = evidence_table or {}

    state_checks = state.get("verification_checks") or []
    state_discrepancies = state.get("discrepancies") or []
    state_verdict = state.get("verdict")
    state_severity = state.get("severity")
    state_risk_score = state.get("risk_score")

    db = SessionLocal()
    checks_list = []
    discrepancies_list = list(state_discrepancies)
    risk_score = float(state_risk_score or 0.0)
    verdict = state_verdict
    bundle_meta = None

    try:
        if bundle_id:
            bundle_obj = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
            if bundle_obj:
                bundle_meta = {
                    "bundle_id": str(bundle_obj.bundle_id),
                    "txn_reference": bundle_obj.txn_reference,
                    "status": bundle_obj.status,
                    "created_at": bundle_obj.created_at.isoformat() if bundle_obj.created_at else None,
                }

            vrun = db.query(VerificationRun).filter(VerificationRun.bundle_id == bundle_id).order_by(VerificationRun.started_at.desc()).first()
            if vrun:
                if not state_checks:
                    checks = db.query(VerificationCheck).filter(VerificationCheck.run_id == vrun.run_id).all()
                    checks_list = [
                        {
                            "check_name": c.check_name,
                            "check_type": c.check_name,
                            "status": c.status,
                            "severity": c.severity,
                            "explanation": c.explanation,
                            "expected": c.expected_value,
                            "actual": c.actual_value,
                            "variance": str(c.variance) if c.variance is not None else None,
                        }
                        for c in checks
                    ]
                if not discrepancies_list:
                    discs = db.query(Discrepancy).filter(Discrepancy.run_id == vrun.run_id).all()
                    discrepancies_list = [
                        {
                            "description": d.description,
                            "severity": d.severity,
                            "category": d.category,
                            "recommended_action": d.recommended_action,
                        }
                        for d in discs
                    ]
                if state_risk_score is None and vrun.overall_risk_score is not None:
                    risk_score = float(vrun.overall_risk_score)
                if not verdict and vrun.overall_status:
                    verdict = "clean" if vrun.overall_status == "clean" else "anomaly"
    except Exception as exc:
        logger.warning(f"[QueryAgent] Error fetching checks from DB: {exc}")

    if state_checks and not checks_list:
        checks_list = [
            {
                "check_name": c.get("check_type", c.get("check_name", "")),
                "check_type": c.get("check_type", c.get("check_name", "")),
                "status": c.get("status"),
                "severity": c.get("severity"),
                "expected": c.get("expected"),
                "actual": c.get("actual"),
                "variance": c.get("variance"),
                "explanation": c.get("explanation"),
            }
            for c in state_checks
        ]

    verification_info = None
    if checks_list or verdict:
        verification_info = {
            "verdict": verdict,
            "severity": state_severity,
            "risk_score": risk_score,
            "checks": checks_list,
            "discrepancies": discrepancies_list,
        }

    answer = _synthesize_answer(user_query, evidence_table, retrieval_plan, verification_info, bundle_id)
    result_metadata = _build_result_metadata(evidence_table, bundle_id)

    # Intent normalization
    intent = "field_lookup"
    is_verif = False
    if retrieval_plan:
        raw_intent = retrieval_plan.get("intent", "lookup")
        if raw_intent in ("comparison", "verification", "full_audit"):
            intent = raw_intent
            is_verif = True
        elif raw_intent == "payment_lookup":
            intent = "payment_lookup"
        else:
            intent = "field_lookup"
        if retrieval_plan.get("verification_required") is True:
            is_verif = True

    # Fetch validated source documents strictly locked to bundle_id
    req_docs = retrieval_plan.get("required_documents") if retrieval_plan else None
    verif_summary = None
    source_docs = []
    try:
        source_docs = _fetch_bundle_source_documents(db, bundle_id, req_docs)
        if is_verif and verification_info:
            verif_summary = _build_structured_verification_summary(
                evidence=evidence_table,
                verification_info=verification_info,
                bundle_id=bundle_id,
                llm_answer=answer,
                db=db,
                required_documents=req_docs,
            )
    except Exception as exc:
        logger.warning(f"[QueryAgent] Error building verification summary: {exc}")
    finally:
        db.close()

    # Standardized response schema
    report_output = {
        "query": user_query,
        "query_type": intent,
        "answer_type": intent,
        "bundle_id": bundle_id,
        "bundle": bundle_meta,
        "answer": answer,
        "result": result_metadata,
        "verification_summary": verif_summary if is_verif else None,
        "financials": (verif_summary.get("financials") if verif_summary and is_verif else None),
        "document_matches": (verif_summary.get("document_matches") if verif_summary and is_verif else None),
        "findings": (verif_summary.get("findings") if verif_summary and is_verif else None),
        "detailed_checks": (verif_summary.get("formatted_checks") if verif_summary and is_verif else None),
        "source_documents": (verif_summary.get("source_documents") if verif_summary and is_verif and verif_summary.get("source_documents") else source_docs),
        "evidence": evidence_table,
        "verification_checks": checks_list if is_verif else [],
        "retrieval_plan": retrieval_plan,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    db = SessionLocal()
    try:
        db.add(
            AgentExecutionLog(
                bundle_id=bundle_id,
                agent_name="query_agent",
                input_snapshot={"user_query": user_query, "bundle_id": bundle_id},
                output_snapshot={"answer": answer},
                latency_ms=int((time.time() - start) * 1000),
                status="success",
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning(f"[QueryAgent] DB log error: {exc}")
    finally:
        db.close()

    return {"report": report_output, "answer": answer}
