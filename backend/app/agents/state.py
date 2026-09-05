from typing import TypedDict, Optional, List, Dict, Any
from typing_extensions import Annotated
import operator

class BundleState(TypedDict):
    bundle_id: str
    user_query: Optional[str]                # Natural language prompt e.g. "Run 4-way verification on TXN-2026-001"
    intent: Optional[str]                    # 'upload_and_extract' | 'verify_bundle' | 'investigate_discrepancies' | 'generate_report' | 'ask_clarification'
    router_decision: Optional[Dict[str, Any]] # Structured RouterDecision output from LLM Router Agent
    txn_reference: Optional[str]             # Transaction reference key extracted from query
    doc_paths: Dict[str, str]                # {'purchase_order': path, 'invoice': path, ...}
    extracted: Dict[str, Any]                # populated per-doc after extraction
    missing_docs: List[str]
    verification_run_id: Optional[str]       # UUID of the VerificationRun persisted to DB
    verification_checks: Annotated[List[Any], operator.add]
    discrepancies: Annotated[List[Any], operator.add]
    risk_score: float
    needs_investigation: bool
    investigation_findings: Optional[Dict[str, Any]]
    report: Optional[Dict[str, Any]]
    errors: Annotated[List[str], operator.add]
