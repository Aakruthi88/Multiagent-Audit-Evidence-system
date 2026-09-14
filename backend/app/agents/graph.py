"""
StateGraph Definition - backend/app/agents/graph.py
---------------------------------------------------
Compiles all agents into a unified StateGraph execution flow.

Architecture:
  User Query
      │
      ▼
  intent_router (Intent Analyzer Planner)
      │
      ├───────────────────────┬────────────────────────┐
      ▼                       ▼                        ▼
  understand              search (Dynamic Retrieval)  search
  (new files upload)      (field lookups)              (verification/report)
      │                       │                        │
      ▼                       ▼                        ▼
    search                  query (QA Agent)         verify
      │                       │                        │
      ▼                       ▼                        ▼
    verify                   END                 report_summary / report_detailed
"""

import time
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from app.agents.document_agent import document_understanding_node
from app.agents.intent_router_agent import intent_router_node
from app.agents.query_agent import query_node
from app.agents.report_agent import (
    report_detailed_node, report_not_found_node, report_summary_node,
)
from app.agents.router_agent import router_node
from app.agents.search_agent import search_node
from app.agents.state import BundleState
from app.agents.verification_agent import verification_node
from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.models import AgentExecutionLog


def log_agent_run(agent_name: str, fn):
    def wrapped(state: BundleState) -> Dict[str, Any]:
        start = time.time()
        bundle_id = state.get("bundle_id")
        logger.info(f"[graph] Starting node '{agent_name}' for bundle '{bundle_id}'")

        out = fn(state)
        latency = int((time.time() - start) * 1000)

        db = SessionLocal()
        try:
            db.add(
                AgentExecutionLog(
                    bundle_id=bundle_id,
                    agent_name=agent_name,
                    input_snapshot={"bundle_id": bundle_id, "action": state.get("action")},
                    output_snapshot={k: v for k, v in (out or {}).items() if k not in ("extracted", "evidence_table")},
                    latency_ms=latency,
                    error_message=(out.get("errors")[0] if (out and out.get("errors")) else None),
                )
            )
            db.commit()
        except Exception as log_exc:
            logger.warning(f"[graph.log_agent_run] Failed to write log: {log_exc}")
        finally:
            db.close()

        return out

    wrapped.__name__ = agent_name
    return wrapped


def understand_node(state: BundleState) -> Dict[str, Any]:
    state_after_router = router_node(state)
    merged = {**state, **state_after_router}
    state_after_extract = document_understanding_node(merged)
    return {**merged, **state_after_extract}


def clarify_node(state: BundleState) -> Dict[str, Any]:
    bundle_id = state.get("bundle_id")
    confidence = state.get("extraction_confidence", 0.0)
    logger.warning(
        f"[ClarifyNode] Bundle {bundle_id} flagged for human review - extraction_confidence={confidence:.2f} < 0.70"
    )
    try:
        from app.models.models import AuditBundle
        db = SessionLocal()
        bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
        if bundle:
            bundle.status = "needs_review"
            db.commit()
        db.close()
    except Exception as exc:
        logger.warning(f"[ClarifyNode] Failed to update bundle status: {exc}")

    return {
        "report": {
            "report_type": "clarification_required",
            "bundle_id": bundle_id,
            "extraction_confidence": confidence,
            "message": (
                f"Extraction confidence {confidence:.0%} is below 70% threshold. "
                "Please review extracted fields manually."
            ),
        }
    }


def _route_after_intent(state: BundleState) -> str:
    action = state.get("action") or "status_query"
    if action == "new_bundle_run":
        logger.info("[graph] Routing after intent: -> 'understand'")
        return "understand"
    logger.info("[graph] Routing after intent: -> 'search'")
    return "search"


def _route_after_understand(state: BundleState) -> str:
    if state.get("errors"):
        logger.info("[graph] Routing after understand: -> 'clarify' (errors present)")
        return "clarify"
    confidence = state.get("extraction_confidence", 1.0)
    if confidence < 0.7:
        logger.info(f"[graph] Routing after understand: -> 'clarify' (confidence {confidence:.2f} < 0.7)")
        return "clarify"
    logger.info("[graph] Routing after understand: -> 'search'")
    return "search"


def _route_after_search(state: BundleState) -> str:
    plan = state.get("retrieval_plan") or {}
    verif_req = plan.get("verification_required")
    report_req = plan.get("report_required")
    action = state.get("action")
    bundle_id = state.get("bundle_id")

    # If no specific bundle_id is resolved, route to query_node for QA / global status synthesis
    if not bundle_id:
        logger.info("[graph] Routing after search: -> 'query' (no resolved bundle_id, delegating to query_node)")
        return "query"

    if verif_req is True or report_req is True or action in ("reverify", "regenerate_report", "new_bundle_run"):
        logger.info(f"[graph] Routing after search: -> 'verify' (verification_required={verif_req}, report_required={report_req}, action='{action}')")
        return "verify"
    logger.info(f"[graph] Routing after search: -> 'query' (lookup query, no verification needed)")
    return "query"


def _route_after_verify(state: BundleState) -> str:
    errors = state.get("errors") or []
    bundle_id = state.get("bundle_id")
    verdict = state.get("verdict", "clean")
    severity = state.get("severity")
    plan = state.get("retrieval_plan") or {}
    report_req = plan.get("report_required")
    action = state.get("action")

    if errors or not bundle_id or verdict == "error":
        logger.info(f"[graph] Routing after verify: -> 'report_not_found' (bundle_id={bundle_id}, verdict={verdict}, errors={errors})")
        return "report_not_found"

    # If full audit / report was requested
    if report_req is True or action in ("regenerate_report", "new_bundle_run"):
        if verdict == "anomaly" or severity == "critical":
            logger.info("[graph] Routing after verify: -> 'report_detailed' (anomaly/critical)")
            return "report_detailed"
        logger.info("[graph] Routing after verify: -> 'report_summary' (clean/warning)")
        return "report_summary"

    # For verification queries (e.g. "Does invoice 200005 match PO 100005?")
    logger.info("[graph] Routing after verify: -> 'query' (conversational answer with verification results)")
    return "query"


workflow = StateGraph(BundleState)

# Nodes
workflow.add_node("intent_router",    log_agent_run("intent_router",    intent_router_node))
workflow.add_node("understand",       log_agent_run("understand",       understand_node))
workflow.add_node("clarify",          log_agent_run("clarify",          clarify_node))
workflow.add_node("search",           log_agent_run("search",           search_node))
workflow.add_node("verify",           log_agent_run("verify",           verification_node))
workflow.add_node("report_summary",   log_agent_run("report_summary",   report_summary_node))
workflow.add_node("report_detailed",  log_agent_run("report_detailed",  report_detailed_node))
workflow.add_node("query",            log_agent_run("query",            query_node))
workflow.add_node("report_not_found", log_agent_run("report_not_found", report_not_found_node))

# Entry Point
workflow.set_entry_point("intent_router")

# Routing Edges
workflow.add_conditional_edges(
    "intent_router",
    _route_after_intent,
    {
        "understand": "understand",
        "search":     "search",
    },
)

workflow.add_conditional_edges(
    "understand",
    _route_after_understand,
    {
        "clarify": "clarify",
        "search":  "search",
    },
)

workflow.add_conditional_edges(
    "search",
    _route_after_search,
    {
        "verify": "verify",
        "query":  "query",
    },
)

workflow.add_conditional_edges(
    "verify",
    _route_after_verify,
    {
        "report_not_found": "report_not_found",
        "report_detailed":  "report_detailed",
        "report_summary":   "report_summary",
        "query":            "query",
    },
)

workflow.add_edge("clarify",          END)
workflow.add_edge("report_not_found", END)
workflow.add_edge("report_summary",   END)
workflow.add_edge("report_detailed",  END)
workflow.add_edge("query",            END)

compiled_graph = workflow.compile()
app_graph = compiled_graph
