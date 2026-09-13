"""
QueryAgent - backend/app/agents/query_agent.py
----------------------------------------------
QA Agent for multi-agent evidence system (TASK 5).

Answers user questions strictly using the retrieved evidence_table
and optional verification results. Never answers from unverified metadata alone.
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.agents.llm_rules import GROUNDING_RULES
from app.agents.state import BundleState
from app.core.config import settings
from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.models import (
    AgentExecutionLog, AuditBundle, BankTransaction,
    Document, GRN, GRNLineItem, Invoice, InvoiceLineItem,
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
        # For direct answers from qwen2.5 (no tags), just pass through.
        thinking_indicators = ["thinking process", "analyze user request", "examine evidence table",
                               "check grounding rules"]
        if any(k in text.lower() for k in thinking_indicators):
            parts = text.split("\n\n")
            non_thinking = [
                p for p in parts
                if not re.match(r"^\d+\.\s*\*\*", p.strip()) and
                   not any(k in p.lower() for k in thinking_indicators)
            ]
            if non_thinking and len(non_thinking) >= len(parts) // 2:
                text = "\n\n".join(non_thinking).strip()
            # If nothing left after stripping, keep original

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
        for f in ("subtotal", "tax_amount", "total_amount", "invoice_date", "due_date", "purchase_order", "po_number"):
            if inv.get(f) is not None:
                doc_inv[f] = inv.get(f)
        if inv.get("line_items"):
            doc_inv["line_items"] = inv.get("line_items")
        filtered["invoice"] = doc_inv

    if "purchase_order" in req_set and po:
        doc_po = {"po_number": po.get("po_number")}
        for f in ("subtotal", "tax_amount", "total_amount", "po_date"):
            if po.get(f) is not None:
                doc_po[f] = po.get(f)
        if po.get("line_items"):
            doc_po["line_items"] = po.get("line_items")
        filtered["purchase_order"] = doc_po

    if "grn" in req_set and grn:
        doc_grn = {"grn_number": grn.get("grn_number")}
        for f in ("grn_date", "delivery_note_number", "received_condition"):
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


def _build_template_answer(user_query: str, evidence: dict, plan: Optional[dict] = None) -> str:
    """Deterministic fallback QA answer grounded strictly in retrieved evidence when LLM is unavailable."""
    q_lower = (user_query or "").lower()
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor_name") or "Vendor"

    if any(k in q_lower for k in ["total", "amount", "subtotal", "tax", "invoice"]) and inv:
        tot = inv.get("total_amount")
        num = inv.get("invoice_number", "N/A")
        if tot is not None:
            return f"Invoice {num} total amount is Rs. {tot:,.2f}."
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
    return "The requested information is not available in the retrieved evidence."


def _build_result_metadata(evidence: dict, bundle_id: Optional[str]) -> dict:
    """Build structured result metadata for frontend display cards."""
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    vendor = evidence.get("vendor_name")

    found = bool(inv or po or evidence.get("grn") or evidence.get("bank_statement"))
    return {
        "found": found,
        "ambiguous": False,
        "bundle_id": bundle_id,
        "vendor_name": vendor,
        "invoice_number": inv.get("invoice_number"),
        "po_number": po.get("po_number"),
        "total_amount": inv.get("total_amount") or po.get("total_amount"),
    }


def _build_intent_system_prompt(intent: str = "") -> str:
    return """You are an audit evidence Query Agent.
Answer the user's exact question using only the supplied evidence and verification results.
Do not invent facts.
If the requested field or line items exist, answer them directly.
Treat deterministic verification results as authoritative.
Ignore unrelated evidence.
Return only the final answer."""


def _synthesize_answer(user_query: str, evidence: dict, plan: Optional[dict] = None, verification_info: Optional[dict] = None) -> str:
    """Synthesize plain-English QA answer via local Ollama strictly grounded in filtered evidence_table & verification results."""
    intent = plan.get("intent", "lookup") if plan else "lookup"

    # Filter evidence to send only relevant documents
    filtered_evidence = _filter_evidence_for_prompt(user_query, evidence, plan)
    logger.info(f"[QueryAgent] Evidence sent to LLM: {json.dumps(filtered_evidence)}")
    evidence_json = json.dumps(filtered_evidence, indent=2)

    system_prompt = _build_intent_system_prompt(intent)

    verif_text = ""
    if verification_info and verification_info.get("checks"):
        verif_text = f"\n\nDeterministic Verification Results (SOURCE OF TRUTH - DO NOT OVERRIDE):\nVerdict: {verification_info.get('verdict', 'N/A').upper()}\nChecks:\n"
        for c in verification_info.get("checks", [])[:10]:
            verif_text += f"- {c.get('check_name')}: {c.get('status', '').upper()} (Expected: {c.get('expected')}, Actual: {c.get('actual')}) - {c.get('explanation')}\n"

    user_prompt = "User question: " + json.dumps(user_query) + "\n\nEvidence Table:\n" + evidence_json + verif_text

    # ── 1. Call Ollama (local qwen2.5:3b) ───────────────────────────────────
    if settings.OLLAMA_HOST:
        try:
            ollama_model = settings.OLLAMA_MODEL or "qwen2.5:3b"
            payload = {
                "model": ollama_model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
                "options": {
                    "num_predict": 300,
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
                "max_tokens": 600,
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

    # ── 3. Explicit LLM generation failure notification ────────────────────
    logger.warning("[QueryAgent] LLM generation unavailable — returning explicit status")
    template_facts = _build_template_answer(user_query, evidence, plan)
    if verification_info and verification_info.get("verdict"):
        verdict_str = verification_info.get("verdict", "").upper()
        return f"[LLM Answer Generation Failure: Local LLM service offline and API key not configured.]\nDeterministic Verification Verdict: {verdict_str}\nGrounded Evidence: {template_facts}"
    return f"[LLM Answer Generation Failure: Local LLM service offline and API key not configured.]\nGrounded Evidence: {template_facts}"


def _fetch_status_bundles(db, query_filters: Optional[dict] = None) -> List[dict]:
    """Fetch bundle status rows from DB for system status queries."""
    try:
        q = db.query(AuditBundle)
        if query_filters:
            if "status" in query_filters:
                q = q.filter(AuditBundle.status == query_filters["status"])
        bundles = q.order_by(AuditBundle.created_at.desc()).limit(50).all()

        rows = []
        for b in bundles:
            # Try to get latest verification run for risk/verdict
            # VerificationRun columns: run_id, bundle_id, started_at, completed_at,
            #   overall_status, overall_risk_score, rules_version
            vrun = (
                db.query(VerificationRun)
                .filter(VerificationRun.bundle_id == b.bundle_id)
                .order_by(VerificationRun.started_at.desc())
                .first()
            )
            failed_checks = []
            risk_score = 0
            overall_status = b.status or "unknown"

            if vrun:
                risk_score = float(vrun.overall_risk_score or 0)
                vrun_status = vrun.overall_status or ""
                if vrun_status in ("anomaly", "critical", "flagged"):
                    overall_status = "flagged"
                elif vrun_status == "clean":
                    overall_status = "clean"

                # VerificationCheck columns: check_id, bundle_id, run_id, check_name,
                #   status, severity, explanation, ...
                failed = (
                    db.query(VerificationCheck)
                    .filter(
                        VerificationCheck.run_id == vrun.run_id,
                        VerificationCheck.status == "fail",
                    )
                    .all()
                )
                failed_checks = [c.check_name for c in failed]

            rows.append({
                "bundle_id": str(b.bundle_id),
                "txn_reference": b.txn_reference,
                "status": overall_status,
                "overall_status": overall_status,
                "risk_score": risk_score,
                "failed_checks": failed_checks,
            })
        return rows
    except Exception as exc:
        logger.warning(f"[QueryAgent] Status bundle fetch error: {exc}")
        return []



def _is_status_query(user_query: str, retrieval_plan: Optional[dict], bundle_id: Optional[str]) -> bool:
    """
    Determine if this is a system-wide bundle status query (no specific bundle resolved).
    Returns True only when there's no resolved bundle_id and the user is asking about
    bundles, flags, statuses, risk scores, or summaries.
    """
    if bundle_id:
        return False
    q = (user_query or "").lower()
    status_keywords = [
        "all bundles", "flagged", "show bundles", "list bundles", "bundles are",
        "high risk", "critical", "which bundles", "how many bundles",
        "show all", "list all", "status", "overview",
    ]
    return any(k in q for k in status_keywords)


def query_node(state: BundleState) -> Dict[str, Any]:
    """LangGraph Node: QA Agent."""
    start = time.time()
    user_query = state.get("user_query") or ""
    bundle_id = state.get("bundle_id")
    evidence_table = state.get("evidence_table")
    retrieval_plan = state.get("retrieval_plan")
    query_filters = state.get("query_filters")

    logger.info(f"[QueryAgent] Answering query: '{user_query}' for bundle {bundle_id}")

    # ── CASE 0: No bundle resolved — vendor/document not found ────────────────
    if not bundle_id and not _is_status_query(user_query, retrieval_plan, bundle_id):
        # Fetch all known vendor names for a helpful response
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
            f"The vendors currently in the system are: {vendor_list_str}. "
            f"Please check the vendor name or try using a PO number (e.g. 'PO 100001') or invoice number."
        )
        logger.warning(f"[QueryAgent] No bundle resolved for query: '{user_query}'. Known vendors: {vendor_list_str}")

        report_output = {
            "query_type": "field_lookup",
            "bundle_id": None,
            "answer": not_found_answer,
            "result": {"found": False, "ambiguous": False, "bundle_id": None},
            "evidence": {},
            "verification_checks": [],
            "retrieval_plan": retrieval_plan,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"report": report_output, "answer": not_found_answer}

    if _is_status_query(user_query, retrieval_plan, bundle_id):
        logger.info("[QueryAgent] Detected system status query - fetching bundle list from DB")
        db = SessionLocal()
        try:
            bundles_list = _fetch_status_bundles(db, query_filters)
        finally:
            db.close()

        report_output = {
            "query_type": "status_query",
            "bundle_id": None,
            "answer": f"Found {len(bundles_list)} audit bundle(s) matching your query.",
            "bundles": bundles_list,
            "result_count": len(bundles_list),
            "filters_applied": query_filters or {},
            "retrieval_plan": retrieval_plan,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        db = SessionLocal()
        try:
            db.add(
                AgentExecutionLog(
                    bundle_id=None,
                    agent_name="query_agent",
                    input_snapshot={"user_query": user_query, "bundle_id": None},
                    output_snapshot={"result_count": len(bundles_list)},
                    latency_ms=int((time.time() - start) * 1000),
                    status="success",
                )
            )
            db.commit()
        except Exception as exc:
            logger.warning(f"[QueryAgent] DB log error: {exc}")
        finally:
            db.close()

        return {"report": report_output, "answer": report_output["answer"]}

    # ── CASE 2: Specific field lookup for a known bundle ──────────────────────
    # If evidence_table not in state yet, fetch from DB
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

    # Build verification_info from state if verification was already run
    verification_info = None
    state_checks = state.get("verification_checks") or []
    state_verdict = state.get("verdict")
    if state_checks or state_verdict:
        verification_info = {
            "verdict": state_verdict,
            "checks": [
                {
                    "check_name": c.get("check_type", c.get("check_name", "")),
                    "status": c.get("status"),
                    "expected": c.get("expected"),
                    "actual": c.get("actual"),
                    "explanation": c.get("explanation"),
                }
                for c in state_checks
            ],
        }

    answer = _synthesize_answer(user_query, evidence_table, retrieval_plan, verification_info)
    result_metadata = _build_result_metadata(evidence_table, bundle_id)

    # Normalize intent to "field_lookup" so the frontend can identify QA responses
    intent = "field_lookup"
    if retrieval_plan:
        raw_intent = retrieval_plan.get("intent", "lookup")
        # Keep payment_lookup as-is; map everything else to field_lookup
        intent = raw_intent if raw_intent == "payment_lookup" else "field_lookup"

    # Fetch verification checks for this bundle if available
    db = SessionLocal()
    checks_list = []
    try:
        if bundle_id:
            vrun = db.query(VerificationRun).filter(VerificationRun.bundle_id == bundle_id).order_by(VerificationRun.started_at.desc()).first()
            if vrun:
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
                    }
                    for c in checks
                ]
    except Exception as exc:
        logger.warning(f"[QueryAgent] Error fetching checks: {exc}")
    finally:
        db.close()

    report_output = {
        "query_type": intent,
        "bundle_id": bundle_id,
        "answer": answer,
        "result": result_metadata,
        "evidence": evidence_table,
        "verification_checks": checks_list,
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
