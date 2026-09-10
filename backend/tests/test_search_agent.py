import pytest
from app.agents.search_agent import _fetch_bundle_evidence, _filter_document_fields
from app.db.session import SessionLocal

def test_filter_document_fields_all():
    raw_header = {"invoice_number": "INV-101", "total_amount": 500.0}
    raw_line_items = [{"description": "Item A", "qty": 2.0}]
    res = _filter_document_fields(raw_header, raw_line_items, "all")
    assert res == {
        "invoice_number": "INV-101",
        "total_amount": 500.0,
        "line_items": [{"description": "Item A", "qty": 2.0}]
    }

def test_filter_document_fields_specific_line_items():
    raw_header = {"grn_number": "GRN-001", "grn_date": "2026-05-01", "received_condition": "Good"}
    raw_line_items = [{"description": "Office Chair", "qty_ordered": 5.0, "qty_received": 3.0, "unit_price": 100.0}]
    res = _filter_document_fields(raw_header, raw_line_items, ["qty_received", "description"])
    assert res == {
        "line_items": [
            {"description": "Office Chair", "qty_received": 3.0}
        ]
    }

def test_filter_document_fields_vendor_only():
    raw_header = {"invoice_number": "INV-101", "vendor_name": "Acme Corp", "total_amount": 1000.0}
    raw_line_items = [{"description": "Item X", "qty": 1.0}]
    res = _filter_document_fields(raw_header, raw_line_items, ["vendor_name"])
    assert res == {"vendor_name": "Acme Corp"}

def test_fetch_bundle_evidence_grn_only():
    db = SessionLocal()
    try:
        # Fetch an existing bundle_id from DB if present
        from app.models.models import AuditBundle
        bundle = db.query(AuditBundle).first()
        if not bundle:
            pytest.skip("No sample audit bundle in DB")

        plan = {
            "required_documents": ["grn"],
            "required_fields": ["qty_received", "description"]
        }
        evidence = _fetch_bundle_evidence(db, str(bundle.bundle_id), plan)
        assert evidence["invoice"] is None
        assert evidence["purchase_order"] is None
        assert evidence["bank_statement"] is None
        if evidence["grn"]:
            assert "grn_number" not in evidence["grn"]
            assert "line_items" in evidence["grn"]
            for item in evidence["grn"]["line_items"]:
                assert "qty_received" in item or "description" in item
    finally:
        db.close()

def test_fetch_bundle_evidence_compare_invoice_po():
    db = SessionLocal()
    try:
        from app.models.models import AuditBundle
        bundle = db.query(AuditBundle).first()
        if not bundle:
            pytest.skip("No sample audit bundle in DB")

        plan = {
            "required_documents": ["invoice", "purchase_order"],
            "required_fields": "all"
        }
        evidence = _fetch_bundle_evidence(db, str(bundle.bundle_id), plan)
        assert evidence["grn"] is None
        assert evidence["bank_statement"] is None
        if evidence["invoice"]:
            assert "invoice_number" in evidence["invoice"]
        if evidence["purchase_order"]:
            assert "po_number" in evidence["purchase_order"]
    finally:
        db.close()
