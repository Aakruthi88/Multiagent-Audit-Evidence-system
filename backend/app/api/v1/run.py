"""
/run API endpoint — backend/app/api/v1/run.py
---------------------------------------------
POST /api/v1/run

Accepts two input shapes:

Shape A — direct action (no LLM classification, saves one call):
  {"bundle_id": "<uuid>", "action": "reverify"}
  {"bundle_id": "<uuid>", "action": "regenerate_report"}
  {"bundle_id": "<uuid>", "action": "new_bundle_run"}

Shape B — natural language query (IntentRouterAgent classifies):
  {"query": "show me all flagged bundles"}
  {"query": "reverify TXN-2026-006"}

Runs the full compiled_graph synchronously and returns a structured summary
of the final state.  For status_query actions the response is the query
results; for pipeline actions the response is the verification/report summary.
"""

from typing import Any, Dict, Optional, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.agents.graph import compiled_graph
from app.core.logging import logger

router = APIRouter(prefix="/run", tags=["run"])

VALID_ACTIONS = {"new_bundle_run", "status_query", "reverify", "regenerate_report"}


# ── Request / Response schemas ─────────────────────────────────────────────────

class RunRequest(BaseModel):
    # Shape A — direct
    bundle_id: Optional[str] = None
    action: Optional[str] = None

    # Shape B — natural language
    query: Optional[str] = None

    # Optional filter pass-through for direct status_query calls
    query_filters: Optional[Dict[str, Any]] = None


class RunResponse(BaseModel):
    bundle_id: Optional[str]
    action: str
    verdict: Optional[str]
    severity: Optional[str]
    risk_score: Optional[float]
    report: Optional[Dict[str, Any]]
    retrieval_plan: Optional[Dict[str, Any]] = None
    required_documents: Optional[List[str]] = None
    errors: list


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("", response_model=RunResponse)
def run_graph(req: RunRequest):
    """
    POST /api/v1/run

    Invoke the LangGraph pipeline for a bundle or a query.

    - If `bundle_id` + `action` are both provided: sets action directly,
      skips IntentRouterAgent LLM call.
    - If only `query` is provided: IntentRouterAgent classifies the action via LLM.
    - If both are provided: direct action takes precedence over query.
    """
    # ── Validate ───────────────────────────────────────────────────────────────
    if not req.bundle_id and not req.query and not req.action:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either 'bundle_id'+'action', or 'query'.",
        )

    if req.action and req.action not in VALID_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action '{req.action}'. Valid: {sorted(VALID_ACTIONS)}",
        )

    # ── Build initial state ────────────────────────────────────────────────────
    initial_state: Dict[str, Any] = {
        # Core
        "bundle_id": req.bundle_id,
        "user_query": req.query,

        # Intent — pre-set if provided directly (skips LLM classification)
        "action": req.action if req.action else None,
        "intent": None,
        "router_decision": None,
        "query_filters": req.query_filters,

        # Doc paths & extraction defaults
        "txn_reference": None,
        "doc_paths": {},
        "extracted": {},
        "missing_docs": [],
        "extraction_confidence": 1.0,

        # Search defaults
        "retrieval_plan": None,
        "evidence_table": None,
        "vendor_similarity_matches": None,

        # Verification defaults
        "verification_run_id": None,
        "verification_checks": [],
        "discrepancies": [],
        "risk_score": 0.0,
        "needs_investigation": False,
        "verdict": None,
        "severity": None,

        # Report / errors
        "investigation_findings": None,
        "report": None,
        "errors": [],
    }

    logger.info(
        f"[POST /run] bundle_id={req.bundle_id} action={req.action} query={req.query!r}"
    )

    # ── Execute graph ──────────────────────────────────────────────────────────
    try:
        final_state = compiled_graph.invoke(initial_state)
    except Exception as exc:
        logger.exception(f"[POST /run] Graph execution error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Graph execution failed: {str(exc)}",
        )

    # ── Build response ────────────────────────────────────────────────────────
    retrieval_plan = final_state.get("retrieval_plan")
    required_docs = None
    if isinstance(retrieval_plan, dict):
        required_docs = retrieval_plan.get("required_documents")
    elif hasattr(retrieval_plan, "required_documents"):
        required_docs = retrieval_plan.required_documents

    if not required_docs and isinstance(final_state.get("report"), dict):
        required_docs = final_state["report"].get("required_documents")

    plan_dump = None
    if isinstance(retrieval_plan, dict):
        plan_dump = retrieval_plan
    elif hasattr(retrieval_plan, "model_dump"):
        plan_dump = retrieval_plan.model_dump()
    elif hasattr(retrieval_plan, "dict"):
        plan_dump = retrieval_plan.dict()

    return RunResponse(
        bundle_id=final_state.get("bundle_id"),
        action=final_state.get("action") or (req.action or "unknown"),
        verdict=final_state.get("verdict"),
        severity=final_state.get("severity"),
        risk_score=final_state.get("risk_score"),
        report=final_state.get("report"),
        retrieval_plan=plan_dump,
        required_documents=required_docs,
        errors=final_state.get("errors") or [],
    )
