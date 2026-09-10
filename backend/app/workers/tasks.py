from app.agents.graph import app_graph
from app.core.logging import logger


def process_bundle_task(bundle_id: str, doc_paths: dict):
    """
    Background worker task: Executes the LangGraph workflow for a newly uploaded bundle.
    Initialises all BundleState fields including the new Day 2 additions.
    """
    logger.info(f"Starting background execution for bundle {bundle_id}")
    initial_state = {
        # Core identifiers
        "bundle_id": str(bundle_id),
        "user_query": None,

        # Intent routing — pre-set so IntentRouterAgent is a no-op pass-through
        "action": "new_bundle_run",
        "intent": None,
        "router_decision": None,
        "query_filters": None,

        # Document paths & extraction
        "txn_reference": None,
        "doc_paths": doc_paths,
        "extracted": {},
        "missing_docs": [],
        "extraction_confidence": 1.0,   # Will be updated by VerificationAgent

        # Search / evidence
        "evidence_table": None,
        "vendor_similarity_matches": None,

        # Verification results
        "verification_run_id": None,
        "verification_checks": [],
        "discrepancies": [],
        "risk_score": 0.0,
        "needs_investigation": False,
        "verdict": None,
        "severity": None,

        # Investigation & reporting
        "investigation_findings": None,
        "report": None,

        # Error accumulation
        "errors": [],
    }

    try:
        final_state = app_graph.invoke(initial_state)
        logger.info(f"Finished background execution for bundle {bundle_id}")
        return final_state
    except Exception as e:
        logger.error(f"Error processing bundle {bundle_id}: {e}")
        return None
