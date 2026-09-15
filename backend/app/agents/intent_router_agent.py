"""
IntentRouterAgent - backend/app/agents/intent_router_agent.py
--------------------------------------------------------------
Intent Analyzer & Retrieval Planner for Multi-Agent Audit System.

Responsibilities:
1. Send user prompt to LLM to create a structured RetrievalPlan JSON (TASK 1).
   Determines required_documents (invoice, purchase_order, grn, bank_statement),
   required_fields, verification_required (bool), and report_required (bool).
2. Resolve bundle_id via SQL database lookup (TASK 2).
3. Populate state["retrieval_plan"], state["bundle_id"], state["action"].
"""

import json
import re
import time
import uuid as _uuid_lib
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import text

from app.agents.state import BundleState
from app.core.config import settings
from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.models import AgentExecutionLog, PurchaseOrder, Invoice, Vendor, BankTransaction


class RetrievalPlan(BaseModel):
    intent: str
    bundle_reference: Optional[str] = None
    required_documents: List[str] = []
    required_fields: Any = []
    verification_required: bool = False
    report_required: bool = False


def _is_valid_bundle_uuid(value) -> bool:
    if not value or not isinstance(value, str):
        return False
    try:
        _uuid_lib.UUID(str(value).strip())
        return True
    except (ValueError, AttributeError, TypeError):
        return False


_PLANNER_SYSTEM_PROMPT = """You are the Intent Analyzer and Retrieval Planner for an enterprise multi-agent audit evidence system.

Your SOLE responsibility is to analyze the user question and return a structured JSON Retrieval Plan.
Do NOT answer the question. Return ONLY valid JSON matching this schema:

{
  "intent": "<lookup | payment_lookup | comparison | full_audit>",
  "bundle_reference": "<string like 'Invoice 200005', 'PO 100005', 'GRN-2026-0005', or null>",
  "required_documents": ["<one or more of: invoice | purchase_order | grn | bank_statement>"],
  "required_fields": ["<field_name1>", "<field_name2>"] or "all",
  "verification_required": <true | false>,
  "report_required": <true | false>
}

CRITICAL RETRIEVAL PLANNING RULES:
1. "required_documents":
   - "invoice": when invoice details (total amount, date, vendor, tax, subtotal) are queried or needed for comparison/audit.
   - "purchase_order": when PO details (items ordered, PO quantity, shipping terms) are queried or needed for comparison/audit.
   - "grn": when goods received / delivery details (qty received, condition, delivery note, GRN number) are queried or needed for comparison/audit.
   - "bank_statement": when bank payment details (payment status, date, bank ref, balance) are queried or needed for comparison/audit.
   - If comparing specific documents (e.g. invoice vs PO vs GRN), include exactly those documents (e.g. ["invoice", "purchase_order", "grn"]).
   - If full audit report is requested, include all 4: ["invoice", "purchase_order", "grn", "bank_statement"].

2. "verification_required":
   - Set to TRUE ONLY if the user explicitly asks to verify, compare documents, run 3-way/4-way match, check for discrepancies, or generate an audit report.
   - Set to FALSE for simple lookups/questions (e.g. "What is the total amount of Invoice 200005?", "How many units were received for GRN-2026-0005?", "What items were ordered in PO 100005?").

3. "report_required":
   - Set to TRUE ONLY if user explicitly asks to generate an audit report.

EXAMPLES:
- "What is the total amount of Invoice 200005?" -> {"intent": "lookup", "bundle_reference": "Invoice 200005", "required_documents": ["invoice"], "required_fields": ["total_amount"], "verification_required": false, "report_required": false}
- "How many units were received for GRN-2026-0005?" -> {"intent": "lookup", "bundle_reference": "GRN-2026-0005", "required_documents": ["grn"], "required_fields": ["qty_received", "line_items"], "verification_required": false, "report_required": false}
- "What items were ordered in PO 100005?" -> {"intent": "lookup", "bundle_reference": "PO 100005", "required_documents": ["purchase_order"], "required_fields": ["line_items"], "verification_required": false, "report_required": false}
- "Show me the key details of TXN-2026-840." -> {"intent": "lookup", "bundle_reference": "TXN-2026-840", "required_documents": ["invoice", "purchase_order", "grn", "bank_statement"], "required_fields": "all", "verification_required": false, "report_required": false}
- "Show me the key details of TXN-2026-935." -> {"intent": "lookup", "bundle_reference": "TXN-2026-935", "required_documents": ["invoice", "purchase_order", "grn", "bank_statement"], "required_fields": "all", "verification_required": false, "report_required": false}
- "Verify invoice 200005 against PO 100005 and GRN-2026-0005" -> {"intent": "comparison", "bundle_reference": "Invoice 200005", "required_documents": ["invoice", "purchase_order", "grn"], "required_fields": "all", "verification_required": true, "report_required": false}
- "Perform a 3-way match for Invoice 200005" -> {"intent": "comparison", "bundle_reference": "Invoice 200005", "required_documents": ["invoice", "purchase_order", "grn"], "required_fields": "all", "verification_required": true, "report_required": false}
- "Generate an audit report for Invoice 200005" -> {"intent": "full_audit", "bundle_reference": "Invoice 200005", "required_documents": ["invoice", "purchase_order", "grn", "bank_statement"], "required_fields": "all", "verification_required": true, "report_required": true}

Return ONLY raw JSON."""


from app.services.entity_resolver import resolve_entities_from_db


def _lookup_bundle_by_query(query: str) -> Optional[str]:
    """Search database for matching bundle_id using entity_resolver."""
    if not query:
        return None
    db = SessionLocal()
    try:
        res = resolve_entities_from_db(db, query)
        if res.get("resolved"):
            return res.get("bundle_id")
    except Exception as exc:
        logger.warning(f"[IntentRouterAgent] Bundle lookup error: {exc}")
    finally:
        db.close()
    return None


def _parse_plan(raw: str) -> Optional[RetrievalPlan]:
    if not raw:
        return None
    text = re.sub(r"```(?:json)?", "", raw, flags=re.I).strip()
    text = re.sub(r"```$", "", text).strip()
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        text = json_match.group(0)
    try:
        return RetrievalPlan.model_validate(json.loads(text))
    except Exception:
        return None


def _call_planner_llm(user_query: str) -> Optional[RetrievalPlan]:
    """Call Ollama LLM to get RetrievalPlan.
    Fallback: OpenRouter -> None (triggers heuristic fallback).
    """
    user_msg = "User question: " + json.dumps(user_query) + "\n\nGenerate the retrieval plan JSON."

    # ── 1. Call Ollama (local qwen2.5:3b) ───────────────────────────────────
    if settings.OLLAMA_HOST:
        try:
            payload = {
                "model": settings.OLLAMA_MODEL or "qwen2.5:3b",
                "prompt": _PLANNER_SYSTEM_PROMPT + "\n\n" + user_msg,
                "format": "json",
                "stream": False,
            }
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                res = client.post(f"{settings.OLLAMA_HOST}/api/generate", json=payload)
                if res.status_code == 200:
                    plan = _parse_plan(res.json().get("response", "{}"))
                    if plan:
                        logger.info(f"[IntentRouterAgent] Using Ollama LLM planner ({settings.OLLAMA_MODEL})")
                        return plan
                    else:
                        logger.warning("[IntentRouterAgent] Ollama planner returned invalid JSON")
                else:
                    logger.warning(f"[IntentRouterAgent] Ollama HTTP {res.status_code}: {res.text}")
        except Exception as exc:
            logger.warning(f"[IntentRouterAgent] Ollama planner error: {exc}")

    # ── 3. Fallback to OpenRouter if key is valid ──────────────────────────
    api_key = settings.OPENROUTER_API_KEY or ""
    if api_key and not api_key.startswith("your_"):
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Audit Intent Analyzer",
            }
            payload = {
                "model": settings.OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "response_format": {"type": "json_object"},
            }
            with httpx.Client(timeout=15.0) as client:
                res = client.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    raw = res.json()["choices"][0]["message"]["content"]
                    plan = _parse_plan(raw)
                    if plan:
                        logger.info("[IntentRouterAgent] Using OpenRouter LLM planner")
                        return plan
        except Exception as exc:
            logger.warning(f"[IntentRouterAgent] OpenRouter planner error: {exc}")

    return None


def _heuristic_fallback_plan(user_query: str) -> RetrievalPlan:
    """Fallback planner ONLY when LLM is offline or fails."""
    q = user_query.lower()
    req_docs = []
    verif = False
    rep = False

    if any(k in q for k in ["quantity", "received", "grn", "delivered", "delivery"]):
        req_docs.append("grn")
    if any(k in q for k in ["paid", "payment", "bank", "ref", "reference", "credited", "debited"]):
        req_docs.append("bank_statement")
    if any(k in q for k in ["vendor", "invoice", "tax", "subtotal", "amount", "due"]):
        req_docs.append("invoice")
    if any(k in q for k in ["po", "purchase order", "ordered", "terms"]):
        req_docs.append("purchase_order")
    if any(k in q for k in ["compare", "verify", "match", "three-way", "3-way", "4-way", "audit report",
                             "audit summary", "generate", "summary", "report"]):
        verif = True
        req_docs = ["invoice", "purchase_order", "grn", "bank_statement"]
    if any(k in q for k in ["report", "summary", "audit report", "audit summary", "generate"]):
        rep = True

    if not req_docs:
        req_docs = ["invoice"]

    intent = "lookup"
    if verif:
        intent = "comparison" if not rep else "full_audit"
    elif "bank_statement" in req_docs:
        intent = "payment_lookup"

    return RetrievalPlan(
        intent=intent,
        bundle_reference=user_query,
        required_documents=list(set(req_docs)),
        required_fields="all",
        verification_required=verif,
        report_required=rep,
    )


def intent_router_node(state: BundleState) -> Dict[str, Any]:
    """LangGraph Node: Intent Analyzer & Retrieval Planner."""
    start = time.time()
    action_in = state.get("action")
    user_query = state.get("user_query") or ""
    bundle_id_input = state.get("bundle_id")

    if action_in == "new_bundle_run":
        logger.info(f"[IntentRouterAgent] Pass-through for new_bundle_run on bundle {bundle_id_input}")
        return {
            "action": "new_bundle_run",
            "bundle_id": bundle_id_input,
        }

    logger.info(f"[IntentRouterAgent] Analyzing query: '{user_query}'")

    plan = _call_planner_llm(user_query)
    if not plan:
        logger.warning("[IntentRouterAgent] LLM planner unavailable - using heuristic fallback plan")
        plan = _heuristic_fallback_plan(user_query)
    else:
        logger.info(f"[IntentRouterAgent] LLM plan adopted directly without heuristic override")

    # Canonical rule: Any audit report, comparison, or verification requires all 4 documents
    if plan.report_required or plan.verification_required or plan.intent in ("full_audit", "comparison", "verification"):
        canonical_4_docs = ["invoice", "purchase_order", "grn", "bank_statement"]
        plan.required_documents = canonical_4_docs

    plan_dict = plan.model_dump()
    logger.info(f"[IntentRouterAgent] Generated RetrievalPlan: {plan_dict}")

    db = SessionLocal()
    resolved_bid = None
    entity_err = None
    matches = []
    try:
        resolution = resolve_entities_from_db(db, user_query)
        if resolution.get("resolved"):
            resolved_bid = resolution.get("bundle_id")
            matches = resolution.get("matches", [])
        else:
            entity_err = resolution.get("error")
            if _is_valid_bundle_uuid(bundle_id_input):
                resolved_bid = str(bundle_id_input).strip()
    finally:
        db.close()

    logger.info(f"[IntentRouterAgent] Resolved bundle_id: {resolved_bid}, matches: {matches}")

    if resolved_bid and (plan.report_required or plan.verification_required):
        action = "reverify"
    else:
        action = "status_query"

    errors_to_add = []
    if entity_err and not resolved_bid:
        errors_to_add.append(json.dumps(entity_err))

    db = SessionLocal()
    try:
        db.add(
            AgentExecutionLog(
                bundle_id=resolved_bid,
                agent_name="intent_router_agent",
                input_snapshot={"user_query": user_query},
                output_snapshot={"retrieval_plan": plan_dict, "resolved_bundle_id": resolved_bid, "matches": matches, "action": action},
                latency_ms=int((time.time() - start) * 1000),
                status="success" if resolved_bid else "warning",
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning(f"[IntentRouterAgent] DB log error: {exc}")
    finally:
        db.close()

    return {
        "retrieval_plan": plan_dict,
        "bundle_id": resolved_bid,
        "action": action,
        "errors": errors_to_add,
    }
