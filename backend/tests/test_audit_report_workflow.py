import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.db.session import SessionLocal
from app.models.models import AuditBundle, Invoice, PurchaseOrder, Report
from app.agents.graph import compiled_graph
from app.agents.intent_router_agent import _fast_path_plan, intent_router_node
from app.agents.graph import _route_after_search, _route_after_verify


def test_fast_path_plan_report_intent_detection():
    """Verify various phrasing of explicit report requests trigger full_audit with report_required=True."""
    report_queries = [
        "Generate an audit report for invoice 200005",
        "Generate audit report for TXN-2026-001",
        "Create an audit report for PO 100005",
        "Audit report for bundle 123",
        "Show audit report for Invoice 200005",
        "Give me an audit report for TXN-2026-840",
        "Generate a report for invoice 200005",
        "Report for TXN-2026-001",
        "Executive summary for PO 100005",
    ]
    for q in report_queries:
        plan = _fast_path_plan(q)
        assert plan is not None, f"Failed to match query: {q}"
        assert plan.intent == "full_audit", f"Intent not full_audit for query: {q}"
        assert plan.report_required is True, f"report_required not True for query: {q}"
        assert plan.verification_required is True, f"verification_required not True for query: {q}"


def test_fast_path_plan_ordinary_query_does_not_request_report():
    """Verify standard lookups and verification queries do NOT set report_required=True."""
    lookup_queries = [
        "What is the total amount of invoice 200005?",
        "How many units were received for GRN-2026-0005?",
        "What items were ordered in PO 100005?",
        "Show me key details of TXN-2026-840",
    ]
    for q in lookup_queries:
        plan = _fast_path_plan(q)
        if plan:
            assert plan.report_required is False, f"report_required was unexpectedly True for lookup: {q}"

    verif_queries = [
        "Verify invoice 200005 against PO 100005 and GRN-2026-0005",
        "Perform a 3-way match for Invoice 200005",
        "Does the invoice match the purchase order?",
    ]
    for q in verif_queries:
        plan = _fast_path_plan(q)
        assert plan is not None
        assert plan.verification_required is True
        assert plan.report_required is False, f"report_required was unexpectedly True for verif: {q}"


def test_routing_decisions_for_report_vs_query():
    """Verify graph routing logic properly branches to report nodes vs query node."""
    # 1. Report request routes to report_summary / report_detailed
    report_state = {
        "bundle_id": "bundle-123",
        "action": "regenerate_report",
        "retrieval_plan": {"verification_required": True, "report_required": True},
        "verdict": "clean",
        "severity": None,
        "errors": [],
    }
    assert _route_after_search(report_state) == "verify"
    assert _route_after_verify(report_state) == "report_summary"

    anomaly_report_state = {
        "bundle_id": "bundle-123",
        "action": "regenerate_report",
        "retrieval_plan": {"verification_required": True, "report_required": True},
        "verdict": "anomaly",
        "severity": "critical",
        "errors": [],
    }
    assert _route_after_verify(anomaly_report_state) == "report_detailed"

    # 2. Ordinary verification query routes to 'query' node (conversational QA)
    verif_query_state = {
        "bundle_id": "bundle-123",
        "action": "reverify",
        "retrieval_plan": {"verification_required": True, "report_required": False},
        "verdict": "clean",
        "severity": None,
        "errors": [],
    }
    assert _route_after_search(verif_query_state) == "verify"
    assert _route_after_verify(verif_query_state) == "query"

    # 3. Lookup query routes directly to 'query' node
    lookup_state = {
        "bundle_id": "bundle-123",
        "action": "status_query",
        "retrieval_plan": {"verification_required": False, "report_required": False},
        "errors": [],
    }
    assert _route_after_search(lookup_state) == "query"


def test_end_to_end_report_query_execution():
    """Test full graph execution when user explicitly requests an audit report on an existing bundle."""
    db = SessionLocal()
    try:
        bundle = db.query(AuditBundle).first()
        if not bundle:
            pytest.skip("No bundle in database")

        inv = db.query(Invoice).filter(Invoice.bundle_id == bundle.bundle_id).first()
        ref = inv.invoice_number if inv and inv.invoice_number else bundle.txn_reference

        query = f"Generate an audit report for {ref}"
        state = {
            "bundle_id": None,
            "user_query": query,
            "action": None,
            "intent": None,
            "router_decision": None,
            "query_filters": None,
            "txn_reference": None,
            "doc_paths": {},
            "extracted": {},
            "missing_docs": [],
            "extraction_confidence": 1.0,
            "retrieval_plan": None,
            "evidence_table": None,
            "vendor_similarity_matches": None,
            "verification_run_id": None,
            "verification_checks": [],
            "discrepancies": [],
            "risk_score": 0.0,
            "needs_investigation": False,
            "verdict": None,
            "severity": None,
            "investigation_findings": None,
            "report": None,
            "errors": []
        }

        res = compiled_graph.invoke(state)
        assert res["bundle_id"] == str(bundle.bundle_id)
        assert res["report"] is not None
        report = res["report"]
        assert report.get("report_type") in ("summary", "detailed")
        assert "executive_summary" in report or "note" in report
        assert "checks_passed" in report
        assert not res.get("errors")
    finally:
        db.close()
