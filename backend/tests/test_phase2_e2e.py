import pytest
from app.db.session import SessionLocal
from app.models.models import AuditBundle, Invoice, PurchaseOrder
from app.agents.graph import compiled_graph
from app.services.entity_resolver import resolve_entities_from_db

def test_entity_resolver_with_live_bundle():
    db = SessionLocal()
    try:
        bundle = db.query(AuditBundle).first()
        if not bundle:
            pytest.skip("No bundle in database")

        inv = db.query(Invoice).filter(Invoice.bundle_id == bundle.bundle_id).first()
        if inv and inv.invoice_number:
            res = resolve_entities_from_db(db, f"What is the total amount for Invoice {inv.invoice_number}?")
            assert res["resolved"] is True
            assert res["bundle_id"] == str(bundle.bundle_id)
            assert any(m["entity_value"] == inv.invoice_number for m in res["matches"])

        po = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == bundle.bundle_id).first()
        if po and po.po_number:
            res_po = resolve_entities_from_db(db, f"Show details for PO {po.po_number}")
            assert res_po["resolved"] is True
            assert res_po["bundle_id"] == str(bundle.bundle_id)
    finally:
        db.close()

def test_graph_lookup_flow_live():
    db = SessionLocal()
    try:
        bundle = db.query(AuditBundle).first()
        if not bundle:
            pytest.skip("No bundle in database")
        
        inv = db.query(Invoice).filter(Invoice.bundle_id == bundle.bundle_id).first()
        if not inv or not inv.invoice_number:
            pytest.skip("No invoice in bundle")
        
        state = {
            "bundle_id": None,
            "user_query": f"What is the total amount for Invoice {inv.invoice_number}?",
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
        assert res["evidence_table"] is not None
        assert res["report"] is not None
        assert not res.get("errors")
    finally:
        db.close()
