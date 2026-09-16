"""
Test suite for Ask Documents query flow bug fixes:
- Separation of FIELD_LOOKUP from AUDIT/VERIFICATION UI
- BUG 1: field_lookup answer contradiction & mutually exclusive found/not-found
- BUG 2: Financial Summary and Detailed Checks data consistency
- BUG 3: Audit report complete AI answer (no truncation)
- BUG 4: Source document count & list consistency
- Baseline comparison & edge cases
"""

import pytest
from app.agents.graph import app_graph
from app.db.session import SessionLocal
from app.models.models import Invoice, AuditBundle


def test_field_lookup_separation_invoice():
    """Query 1: What is the total of Invoice 200005? -> Field lookup only."""
    query = "What is the total of Invoice 200005?"
    res = app_graph.invoke({"user_query": query})
    report = res.get("report") or {}
    answer = res.get("answer") or report.get("answer") or ""

    assert "637,200" in answer or "637200" in answer, f"Expected 637,200 in answer, got: {answer}"
    assert report.get("verification_summary") is None, "verification_summary must be None for field_lookup"
    assert report.get("query_type") == "field_lookup"
    assert report.get("result", {}).get("status") == "VERIFIED"
    assert report.get("result", {}).get("found") is True


def test_field_lookup_separation_po_items():
    """Query 2: What items were ordered in PO 100005? -> Field lookup only."""
    query = "What items were ordered in PO 100005?"
    res = app_graph.invoke({"user_query": query})
    report = res.get("report") or {}
    answer = res.get("answer") or report.get("answer") or ""

    assert "projector" in answer.lower() or "full hd" in answer.lower(), f"Expected projector in answer, got: {answer}"
    assert report.get("verification_summary") is None, "verification_summary must be None for field_lookup"
    assert report.get("query_type") == "field_lookup"
    assert report.get("result", {}).get("status") == "VERIFIED"


def test_field_lookup_txn_840():
    """Query 3: Show me the key details of a bundle transaction. -> Field lookup only."""
    db = SessionLocal()
    bundle = db.query(AuditBundle).filter(AuditBundle.txn_reference != None).first()
    txn_ref = bundle.txn_reference if bundle else "TXN-2026-895"
    db.close()

    query = f"Show me the key details of {txn_ref}."
    res = app_graph.invoke({"user_query": query})
    report = res.get("report") or {}

    assert report.get("verification_summary") is None, "verification_summary must be None for field_lookup"
    assert report.get("query_type") == "field_lookup"
    assert report.get("result", {}).get("status") == "VERIFIED"


def test_field_lookup_txn_935():
    """Query 4: Show me the key details of another bundle transaction. -> Field lookup only."""
    db = SessionLocal()
    bundle = db.query(AuditBundle).filter(AuditBundle.txn_reference != None).offset(1).first()
    txn_ref = bundle.txn_reference if bundle else "TXN-2026-895"
    db.close()

    query = f"Show me the key details of {txn_ref}."
    res = app_graph.invoke({"user_query": query})
    report = res.get("report") or {}

    assert report.get("verification_summary") is None, "verification_summary must be None for field_lookup"
    assert report.get("query_type") == "field_lookup"
    assert report.get("result", {}).get("status") == "VERIFIED"


def test_baseline_comparison():
    """Query 5: Verify invoice 200005 against PO 100005 and GRN-2026-0005."""
    query = "Verify invoice 200005 against PO 100005 and GRN-2026-0005"
    res = app_graph.invoke({"user_query": query})

    report = res.get("report") or {}
    verif = report.get("verification_summary") or report
    assert verif is not None
    checks = verif.get("formatted_checks") or verif.get("verification_checks") or []
    assert len(checks) >= 15, f"Expected >= 15 checks, got {len(checks)}"

    fin = verif.get("financials") or report.get("financials") or {}
    assert fin.get("invoice_total") == 637200.0
    assert fin.get("po_total") == 637200.0


def test_audit_report():
    """Query 6: Generate an audit report for invoice 200005."""
    query = "Generate an audit report for invoice 200005"
    res = app_graph.invoke({"user_query": query})

    report = res.get("report") or {}
    summary = report.get("executive_summary") or report.get("note") or report.get("narrative") or ""

    assert len(summary) > 100, f"Summary too short: {summary}"
    assert summary.strip().endswith((".", "!", '"', "'", ")")), f"Summary appears truncated: {summary[-50:]}"

    source_docs = report.get("source_documents") or []
    doc_types = {d.get("doc_type") for d in source_docs}
    assert {"invoice", "purchase_order", "grn", "bank_statement"}.issubset(doc_types), f"Expected all 4 doc types, got: {doc_types}"
    assert len(source_docs) == 4, f"Expected exactly 4 source documents, got {len(source_docs)}"


def test_negative_nonexistent_invoice():
    """Negative case: Nonexistent invoice."""
    query = "What is the total of Invoice 999999?"
    res = app_graph.invoke({"user_query": query})

    report = res.get("report") or {}
    answer = res.get("answer") or report.get("answer") or ""
    neg_phrases = ["no matching", "not found", "not available", "not mentioned", "cannot find", "no information"]
    assert any(p in answer.lower() for p in neg_phrases), f"Expected negative statement, got: {answer}"
    assert report.get("result", {}).get("found") is False
    assert report.get("result", {}).get("status") in ("NOT FOUND", "INSUFFICIENT EVIDENCE")
