import pytest
from app.db.session import SessionLocal
from app.models.models import AuditBundle, Invoice, Vendor
from app.services.entity_resolver import resolve_entities_from_db, semantic_search_documents
from app.agents.graph import compiled_graph

def test_exact_id_query_still_works():
    db = SessionLocal()
    try:
        bundle = db.query(AuditBundle).first()
        if not bundle:
            pytest.skip("No sample audit bundle in DB")
        inv = db.query(Invoice).filter(Invoice.bundle_id == bundle.bundle_id).first()
        if not inv or not inv.invoice_number:
            pytest.skip("No invoice found in bundle")

        res = resolve_entities_from_db(db, f"What is the total amount for Invoice {inv.invoice_number}?")
        assert res["resolved"] is True
        assert res["bundle_id"] == str(bundle.bundle_id)
        assert any(m["entity_type"] == "invoice_number" for m in res["matches"])
    finally:
        db.close()

def test_descriptive_vendor_query():
    db = SessionLocal()
    try:
        vendor = db.query(Vendor).first()
        if not vendor:
            pytest.skip("No vendor in DB")

        vname = vendor.name_normalized or vendor.name_raw
        query = f"Find the invoice related to {vname}"
        res = resolve_entities_from_db(db, query)
        assert res["resolved"] is True
        assert res["bundle_id"] is not None
        assert any(m["entity_type"] in ("vendor_name", "semantic_search") for m in res["matches"])
    finally:
        db.close()

def test_descriptive_payment_evidence_query():
    db = SessionLocal()
    try:
        query = "Show documents supporting the payment to Oak PLC Traders"
        res = resolve_entities_from_db(db, query)
        assert res["resolved"] is True
        assert res["bundle_id"] is not None
    finally:
        db.close()

def test_semantic_ranking_and_bundle_preservation():
    db = SessionLocal()
    try:
        results = semantic_search_documents(db, "Oak PLC Traders invoice total amount", top_k=3)
        assert len(results) > 0
        for item in results:
            assert "bundle_id" in item
            assert item["bundle_id"] is not None
            assert "doc_type" in item
            assert "score" in item
            assert item["score"] >= 0.0
    finally:
        db.close()

def test_no_relevant_evidence():
    db = SessionLocal()
    try:
        res = resolve_entities_from_db(db, "Which document contains quantum submarine navigation manual?")
        # Should either resolve to False or return ENTITY_NOT_FOUND error
        if not res["resolved"]:
            assert res["bundle_id"] is None
            assert res.get("error") is not None
    finally:
        db.close()

def test_discrepancies_query_graph():
    db = SessionLocal()
    try:
        bundle = db.query(AuditBundle).first()
        if not bundle:
            pytest.skip("No bundle in DB")

        state = {
            "bundle_id": str(bundle.bundle_id),
            "user_query": "Find discrepancies between the documents.",
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

        out = compiled_graph.invoke(state)
        assert out.get("bundle_id") is not None
        assert out.get("report") is not None
    finally:
        db.close()
