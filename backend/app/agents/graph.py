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
import uuid
from typing import Any, Dict, Optional

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
from app.db.checkpointer import get_checkpointer
from app.db.session import SessionLocal
from app.models.models import AgentExecutionLog


def log_agent_run(agent_name: str, fn):
    def wrapped(state: BundleState) -> Dict[str, Any]:
        start = time.time()
        bundle_id = state.get("bundle_id")
        logger.info(f"[graph] Starting node '{agent_name}' for bundle '{bundle_id}'")

        out = fn(state) or {}
        latency_ms = int((time.time() - start) * 1000)
        logger.info(f"⏱️  [AGENT TIMING] {agent_name}: {latency_ms}ms ({latency_ms / 1000:.2f}s)")

        # Record agent timings dictionary in output state
        existing_timings = dict(state.get("agent_timings") or {})
        existing_timings[agent_name] = latency_ms
        out["agent_timings"] = existing_timings

        db = SessionLocal()
        try:
            db.add(
                AgentExecutionLog(
                    bundle_id=bundle_id,
                    agent_name=agent_name,
                    input_snapshot={"bundle_id": bundle_id, "action": state.get("action")},
                    output_snapshot={k: v for k, v in out.items() if k not in ("extracted", "evidence_table", "agent_timings")},
                    latency_ms=latency_ms,
                    error_message=(out.get("errors")[0] if out.get("errors") else None),
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

# Checkpointer initialization (PostgreSQL / SQLite / Fallback)
checkpointer = get_checkpointer()
_compiled_inner = workflow.compile(checkpointer=checkpointer)


class CheckpointedStateGraph:
    """
    Thread-isolated wrapper around LangGraph CompiledStateGraph.
    Guarantees state isolation across concurrent audit bundles and user queries:
    - Derives deterministic thread_id from bundle_id or txn_reference if not passed in config.
    - Preserves existing invoke(), get_state(), get_state_history(), and update_state() APIs.
    - Persists execution state to PostgreSQL (production) or SQLite (development/test).
    """

    def __init__(self, inner_graph, checkpointer_obj):
        self._inner = inner_graph
        self.checkpointer = checkpointer_obj

    def invoke(self, input: Dict[str, Any], config: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        cfg = dict(config) if config else {}
        configurable = dict(cfg.get("configurable") or {})
        if "thread_id" not in configurable:
            thread_id = None
            if isinstance(input, dict):
                thread_id = input.get("bundle_id") or input.get("txn_reference")
            if not thread_id:
                thread_id = f"session_{uuid.uuid4()}"
            configurable["thread_id"] = str(thread_id)
            cfg["configurable"] = configurable

        pipeline_start = time.time()
        final_state = self._inner.invoke(input, config=cfg, **kwargs)
        total_time_ms = int((time.time() - pipeline_start) * 1000)

        if isinstance(final_state, dict):
            final_state["total_pipeline_time_ms"] = total_time_ms
            timings = final_state.get("agent_timings") or {}
            user_query = input.get("user_query") if isinstance(input, dict) else None
            bundle_ref = final_state.get("bundle_id") or "N/A"
            action_ref = final_state.get("action") or "query"

            summary_box = [
                "",
                "=" * 70,
                "⏱️  BACKEND QUERY & AGENT TIMING BREAKDOWN",
                "=" * 70,
                f"• Query / Action : {user_query or action_ref}",
                f"• Target Bundle  : {bundle_ref}",
                "-" * 70,
            ]
            for agent, t_ms in timings.items():
                summary_box.append(f"  • {agent:<20} : {t_ms:>5} ms  ({t_ms / 1000:>5.2f}s)")
            summary_box.append("-" * 70)
            summary_box.append(f"🏁 TOTAL PIPELINE TIME  : {total_time_ms:>5} ms  ({total_time_ms / 1000:>5.2f}s)")
            summary_box.append("=" * 70)
            
            logger.info("\n".join(summary_box))

        return final_state

    def get_state(self, config: Dict[str, Any], **kwargs):
        return self._inner.get_state(config, **kwargs)

    def get_state_history(self, config: Dict[str, Any], **kwargs):
        return self._inner.get_state_history(config, **kwargs)

    def update_state(self, config: Dict[str, Any], values: Dict[str, Any], as_node: Optional[str] = None):
        return self._inner.update_state(config, values, as_node=as_node)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


compiled_graph = CheckpointedStateGraph(_compiled_inner, checkpointer)
app_graph = compiled_graph

