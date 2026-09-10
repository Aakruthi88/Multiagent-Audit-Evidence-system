from typing import TypedDict, Optional, List, Dict, Any
from typing_extensions import Annotated
import operator


class BundleState(TypedDict):
    # ── Core identifiers ────────────────────────────────────────────────────────
    bundle_id: Optional[str]
    user_query: Optional[str]            # Natural language prompt

    # ── Intent routing ───────────────────────────────────────────────────────────
    action: Optional[str]                # Determined by IntentRouterAgent or set directly by API:
                                         # "new_bundle_run" | "status_query" | "reverify" | "regenerate_report"
    intent: Optional[str]                # Legacy field kept for backward compat with existing RouterAgent
    router_decision: Optional[Dict[str, Any]]   # Structured RouterDecision from existing RouterAgent
    query_filters: Optional[Dict[str, Any]]     # e.g. {"status": "flagged"} for status_query action

    # ── Document paths & extraction ──────────────────────────────────────────────
    txn_reference: Optional[str]         # e.g. "TXN-2026-001"
    doc_paths: Dict[str, str]            # {'purchase_order': path, 'invoice': path, ...}
    extracted: Dict[str, Any]            # Populated per-doc after DocumentAgent runs
    missing_docs: List[str]
    extraction_confidence: float         # Min confidence across all documents in bundle (0.0–1.0)

    # ── Search / evidence alignment ──────────────────────────────────────────────
    retrieval_plan: Optional[Dict[str, Any]]
    evidence_table: Optional[Dict[str, Any]]          # Cross-doc field alignment built by SearchAgent
    vendor_similarity_matches: Optional[List[Any]]    # ChromaDB top-3 similar vendors from other bundles

    # ── Verification results ─────────────────────────────────────────────────────
    verification_run_id: Optional[str]
    verification_checks: List[Any]
    discrepancies: List[Any]
    risk_score: float
    needs_investigation: bool
    verdict: Optional[str]               # "clean" | "anomaly"  — set by VerificationAgent
    severity: Optional[str]              # "critical" | "warning" | None — set by VerificationAgent

    # ── Investigation & reporting ────────────────────────────────────────────────
    investigation_findings: Optional[Dict[str, Any]]
    report: Optional[Dict[str, Any]]

    # ── Error accumulation ───────────────────────────────────────────────────────
    errors: List[str]
