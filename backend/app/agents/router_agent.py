import json
import time
import re
import httpx
from typing import Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.agents.state import BundleState
from app.schemas.router_schemas import RouterDecision
from app.models.models import AgentExecutionLog
from app.db.session import SessionLocal

EXPECTED_DOC_TYPES = ["purchase_order", "invoice", "grn", "bank_statement"]

class LLMRouterService:
    def classify_query(self, user_query: str, bundle_id: Optional[str] = None, doc_paths: Optional[Dict[str, str]] = None) -> RouterDecision:
        """
        Production-Ready LLM Router Agent:
        Analyzes natural language user queries using an LLM (OpenRouter/Ollama) with strict Pydantic JSON validation.
        """
        start_time = time.time()
        query_text = (user_query or "").strip()
        
        logger.info(f"[Router Agent] Analyzing query: '{query_text}' (Bundle ID: {bundle_id})")

        decision = None
        model_used = "llm_fallback_router"
        tokens_used = 0

        # 1. OpenRouter LLM Call
        if settings.OPENROUTER_API_KEY and query_text:
            decision, model_used, tokens_used = self._call_openrouter_llm(query_text, bundle_id)
        
        # 2. Ollama Local LLM Fallback
        if not decision and settings.OLLAMA_HOST and query_text:
            decision, model_used, tokens_used = self._call_ollama_llm(query_text, bundle_id)

        # 3. Intelligent Deterministic Fallback Parser (Offline/Keyless Mode)
        if not decision:
            logger.info("[Router Agent] LLM unavailable or fallback required — using structured decision parser.")
            decision = self._parse_structured_decision(query_text, bundle_id, doc_paths)
            model_used = "llm_structured_fallback_v1"

        latency_ms = int((time.time() - start_time) * 1000)

        # Log agent execution
        try:
            db = SessionLocal()
            log_entry = AgentExecutionLog(
                bundle_id=bundle_id if bundle_id else None,
                agent_name="router_agent",
                input_snapshot={"user_query": query_text, "doc_paths_count": len(doc_paths or {})},
                output_snapshot=decision.model_dump(),
                model_used=model_used,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                status="success"
            )
            db.add(log_entry)
            db.commit()
            db.close()
        except Exception as e:
            logger.warning(f"[Router Agent] Failed to save execution log: {e}")

        logger.info(
            f"[Router Agent] Decision: Intent='{decision.user_intent}' -> Target='{decision.target_workflow}' | "
            f"TxnRef='{decision.txn_reference}' | Confidence={decision.confidence}"
        )
        return decision

    def _call_openrouter_llm(self, query: str, bundle_id: Optional[str]) -> Tuple[Optional[RouterDecision], str, int]:
        system_prompt = """You are the Router Agent for an Enterprise Multi-Agent Audit Evidence System.
Your job is to analyze the user's natural language input and return a JSON decision strictly matching the Pydantic schema.

Valid Workflows & Intents:
1. 'document_understanding' ('upload_and_extract'): User wants to extract, parse, upload, or read PDF evidence files.
2. 'verification' ('verify_bundle'): User wants to run 4-way match rules, verify numbers, subtotal/tax, PO vs Invoice totals, or check date sequences.
3. 'search_investigation' ('investigate_discrepancies'): User wants to check duplicate invoices across bundles, check vendor history, or search anomalies.
4. 'report_generation' ('generate_report'): User wants to generate, view, export, or summarize the PDF audit report.
5. 'clarification' ('ask_clarification'): Query is ambiguous, or missing required transaction reference when required.

Extract transaction references like 'TXN-2026-001', 'TXN-2026-006', or numeric IDs like '100001'.
Do NOT execute downstream agent logic. Only output valid JSON matching the schema.
"""
        user_prompt = f"User Query: {query}\nContext Bundle ID: {bundle_id or 'None'}\n\nJSON Schema:\n{RouterDecision.model_json_schema()}"

        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Audit Evidence Assistant Router"
        }
        payload = {
            "model": settings.OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"}
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    tokens = data.get("usage", {}).get("total_tokens", 0)
                    parsed = json.loads(content)
                    validated = RouterDecision.model_validate(parsed)
                    return validated, f"openrouter/{settings.OPENROUTER_MODEL}", tokens
        except Exception as e:
            logger.warning(f"[Router Agent] OpenRouter API error: {e}")
        return None, "openrouter", 0

    def _call_ollama_llm(self, query: str, bundle_id: Optional[str]) -> Tuple[Optional[RouterDecision], str, int]:
        prompt = f"Classify audit query in JSON: {query}. Target workflows: document_understanding, verification, search_investigation, report_generation, clarification."
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "format": "json",
            "stream": False
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(f"{settings.OLLAMA_HOST}/api/generate", json=payload)
                if res.status_code == 200:
                    parsed = json.loads(res.json().get("response", "{}"))
                    validated = RouterDecision.model_validate(parsed)
                    return validated, f"ollama/{settings.OLLAMA_MODEL}", 0
        except Exception as e:
            logger.warning(f"[Router Agent] Ollama API error: {e}")
        return None, "ollama", 0

    def _parse_structured_decision(self, query: str, bundle_id: Optional[str], doc_paths: Optional[Dict[str, str]]) -> RouterDecision:
        """Structured parser simulating LLM reasoning for offline/test environments."""
        q = query.lower()
        
        # Extract transaction reference if mentioned e.g. TXN-2026-001 or TXN-2026-006
        txn_match = re.search(r'(TXN[-_]?2026[-_]?\d{3}|\bTXN\d+\b)', query, re.I)
        txn_ref = txn_match.group(1).upper() if txn_match else None

        # Check if reference is required but missing (e.g., "verify transaction" without specifying which)
        if not txn_ref and not bundle_id and not doc_paths and query.strip().lower() in ["run verification", "verify", "check", "investigate", "report"]:
            return RouterDecision(
                user_intent="ask_clarification",
                target_workflow="clarification",
                txn_reference=None,
                bundle_id=bundle_id,
                filters={},
                confidence=0.9,
                requires_clarification=True,
                clarification_message="Please specify the transaction reference (e.g. TXN-2026-001) or attach document evidence.",
                explanation="Query requested action but no transaction reference or uploaded documents were provided."
            )

        # Classification logic
        if any(k in q for k in ["verify", "verification", "check numbers", "4-way", "mismatch", "recompute", "rule", "audit check"]):
            return RouterDecision(
                user_intent="verify_bundle",
                target_workflow="verification",
                txn_reference=txn_ref,
                bundle_id=bundle_id,
                filters={"rule_set": "all"},
                confidence=0.95,
                requires_clarification=False,
                explanation="User query requests 4-way match rule verification."
            )

        elif any(k in q for k in ["search", "investigate", "duplicate", "history", "vendor history", "cross-bundle", "fraud"]):
            return RouterDecision(
                user_intent="investigate_discrepancies",
                target_workflow="search_investigation",
                txn_reference=txn_ref,
                bundle_id=bundle_id,
                filters={"scope": "cross_bundle"},
                confidence=0.92,
                requires_clarification=False,
                explanation="User query requests cross-bundle duplicate/vendor investigation."
            )

        elif any(k in q for k in ["report", "pdf", "export", "summary", "narrative", "generate report", "download"]):
            return RouterDecision(
                user_intent="generate_report",
                target_workflow="report_generation",
                txn_reference=txn_ref,
                bundle_id=bundle_id,
                filters={"format": "pdf"},
                confidence=0.94,
                requires_clarification=False,
                explanation="User query requests audit report generation."
            )

        else:
            # Default / Upload & Extract workflow
            return RouterDecision(
                user_intent="upload_and_extract",
                target_workflow="document_understanding",
                txn_reference=txn_ref,
                bundle_id=bundle_id,
                filters={},
                confidence=0.90,
                requires_clarification=False,
                explanation="User query or document upload targeted for text extraction and document understanding."
            )

router_service = LLMRouterService()

def router_node(state: BundleState) -> BundleState:
    """
    Router Agent LangGraph Node:
    - First node in the processing graph
    - Calls LLMRouterService to classify user query
    - Sets missing_docs and router_decision in BundleState
    """
    bundle_id = state.get("bundle_id")
    user_query = state.get("user_query") or ""
    doc_paths = state.get("doc_paths", {})
    provided_types = set(doc_paths.keys())

    # Execute LLM Router Decision
    decision: RouterDecision = router_service.classify_query(
        user_query=user_query,
        bundle_id=bundle_id,
        doc_paths=doc_paths
    )

    missing_docs = [dt for dt in EXPECTED_DOC_TYPES if dt not in provided_types]

    return {
        **state,
        "intent": decision.user_intent,
        "txn_reference": decision.txn_reference or state.get("txn_reference"),
        "router_decision": decision.model_dump(),
        "missing_docs": missing_docs,
        "errors": []
    }
