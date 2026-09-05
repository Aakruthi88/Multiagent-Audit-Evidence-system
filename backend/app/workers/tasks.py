from app.agents.graph import app_graph
from app.core.logging import logger

def process_bundle_task(bundle_id: str, doc_paths: dict):
    """
    Background worker task: Executes the LangGraph workflow for a newly uploaded bundle.
    """
    logger.info(f"Starting background execution for bundle {bundle_id}")
    initial_state = {
        "bundle_id": str(bundle_id),
        "doc_paths": doc_paths,
        "extracted": {},
        "missing_docs": [],
        "verification_checks": [],
        "discrepancies": [],
        "risk_score": 0.0,
        "needs_investigation": False,
        "investigation_findings": None,
        "report": None,
        "errors": []
    }
    
    try:
        final_state = app_graph.invoke(initial_state)
        logger.info(f"Finished background execution for bundle {bundle_id}")
        return final_state
    except Exception as e:
        logger.error(f"Error processing bundle {bundle_id}: {e}")
        return None
