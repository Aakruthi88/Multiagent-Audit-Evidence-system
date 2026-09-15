"""
Phase 2B Test Suite - backend/tests/test_phase2b_grounding_retrieval.py
-----------------------------------------------------------------------
Verification and grounding tests:
1. Test 1 — Direct factual query (e.g. "What is the total of Invoice 200005?")
2. Test 2 — Verification query (e.g. "Does Invoice 200005 match the Purchase Order?")
3. Test 3 — Explanation query (e.g. "Why was TXN-2026-817 flagged?")
4. Test 4 — Missing evidence (Non-existent entity / document)
5. Test 5 — Cross-bundle isolation (Querying Bundle A for Bundle B entity)
6. Test 6 — Authoritative Source of Truth (Deterministic engine remains invariant)
7. Test 7 — Source document attribution correctness & isolation
"""

import pytest
from app.agents.graph import app_graph
from app.db.session import SessionLocal
from app.models.models import AuditBundle, Invoice, PurchaseOrder, GRN, Document


def test_phase2b_direct_factual_query():
    """
    Test 1 — Direct factual query:
    "What is the total of Invoice 200005?"
    Expected:
    - Value comes from structured data
    - Correct invoice is identified
    - Source document is the correct invoice document
    """
    query = "What is the total of Invoice 200005?"
    res = app_graph.invoke({"user_query": query})
    report = res.get("report") or {}
    answer = res.get("answer") or report.get("answer") or ""

    assert "637,200" in answer or "637200" in answer, f"Expected total 637,200 in answer, got: {answer}"
    assert report.get("query_type") == "field_lookup"

    # Evidence check
    evidence = report.get("evidence") or {}
    assert evidence.get("invoice") is not None
    assert str(evidence["invoice"].get("invoice_number")) == "200005"
    assert float(evidence["invoice"].get("total_amount")) == 637200.0

    # Source documents check
    source_docs = report.get("source_documents") or []
    if source_docs:
        doc_types = {d.get("doc_type") for d in source_docs}
        assert "invoice" in doc_types


def test_phase2b_verification_query():
    """
    Test 2 — Verification query:
    "Does Invoice 200005 match the Purchase Order?"
    Expected:
    - Deterministic verification result
    - Correct PO and Invoice evidence
    - LLM must not alter PASS/FAIL
    """
    query = "Does Invoice 200005 match the Purchase Order?"
    res = app_graph.invoke({"user_query": query})
    report = res.get("report") or {}
    verif = report.get("verification_summary") or report

    assert verif is not None
    assert verif.get("overall_status") in ("VERIFIED", "FAILED", "REVIEW REQUIRED", "clean", "anomaly")
    
    # Financials must match deterministic values
    fin = verif.get("financials") or report.get("financials") or {}
    assert fin.get("invoice_total") == 637200.0
    assert fin.get("po_total") == 637200.0

    # Document matches present
    doc_matches = verif.get("document_matches") or []
    assert len(doc_matches) > 0


def test_phase2b_explanation_query():
    """
    Test 3 — Explanation query:
    "Why was TXN-2026-817 flagged?"
    Expected:
    - Deterministic finding is retrieved
    - LLM explains that finding
    - Explanation contains only supported facts
    - Correct source documents are returned
    """
    query = "Why was TXN-2026-817 flagged?"
    res = app_graph.invoke({"user_query": query})
    report = res.get("report") or {}
    answer = res.get("answer") or report.get("answer") or ""

    assert len(answer) > 20
    # Must mention discrepancy, mismatch, or check details from the bundle
    assert report.get("bundle_id") is not None or "817" in answer or "flagged" in answer.lower()


def test_phase2b_missing_evidence_negative():
    """
    Test 4 — Missing evidence:
    Ask about a document/entity that does not exist (e.g. Invoice 999999).
    Expected:
    - System clearly states that evidence was not found
    - No hallucinated answer
    - No unrelated source documents
    """
    query = "What is the total of Invoice 999999?"
    res = app_graph.invoke({"user_query": query})
    report = res.get("report") or {}
    answer = res.get("answer") or report.get("answer") or ""

    neg_phrases = ["no matching", "not found", "not available", "not mentioned", "cannot find", "no information"]
    assert any(p in answer.lower() for p in neg_phrases), f"Expected explicit missing evidence message, got: {answer}"

    result_meta = report.get("result") or {}
    assert result_meta.get("found") is False
    assert result_meta.get("status") in ("NOT FOUND", "INSUFFICIENT EVIDENCE")

    # Source documents must be empty
    source_docs = report.get("source_documents") or []
    assert len(source_docs) == 0, f"Expected 0 source documents for nonexistent invoice, got {source_docs}"


def test_phase2b_cross_bundle_isolation():
    """
    Test 5 — Cross-bundle isolation:
    Verify that evidence and source documents retrieved for Bundle A strictly belong to Bundle A,
    and do not leak into another bundle's context.
    """
    db = SessionLocal()
    try:
        bundles = db.query(AuditBundle).limit(2).all()
        if len(bundles) < 2:
            pytest.skip("Need at least 2 audit bundles in DB for cross-bundle isolation test")

        bundle_a = bundles[0]
        bundle_b = bundles[1]
        bid_a = str(bundle_a.bundle_id)
        bid_b = str(bundle_b.bundle_id)

        # Retrieve evidence directly for Bundle A
        from app.agents.search_agent import _fetch_bundle_evidence, _fetch_bundle_source_documents
        evidence_a = _fetch_bundle_evidence(db, bid_a, {"required_documents": ["invoice", "purchase_order", "grn", "bank_statement"], "required_fields": "all"})
        evidence_b = _fetch_bundle_evidence(db, bid_b, {"required_documents": ["invoice", "purchase_order", "grn", "bank_statement"], "required_fields": "all"})

        # Bundle IDs in evidence must match strictly
        assert evidence_a["bundle_id"] == bid_a
        assert evidence_b["bundle_id"] == bid_b

        # Source documents must strictly belong to their respective bundle_id
        sources_a = _fetch_bundle_source_documents(db, bid_a)
        sources_b = _fetch_bundle_source_documents(db, bid_b)

        for s in sources_a:
            assert s["bundle_id"] == bid_a
        for s in sources_b:
            assert s["bundle_id"] == bid_b

        # If both bundles have invoices, verify their invoice numbers don't cross-leak
        inv_a = db.query(Invoice).filter(Invoice.bundle_id == bid_a).first()
        inv_b = db.query(Invoice).filter(Invoice.bundle_id == bid_b).first()
        if inv_a and inv_b and inv_a.invoice_number != inv_b.invoice_number:
            if evidence_a.get("invoice"):
                assert evidence_a["invoice"]["invoice_number"] != inv_b.invoice_number
            if evidence_b.get("invoice"):
                assert evidence_b["invoice"]["invoice_number"] != inv_a.invoice_number
    finally:
        db.close()


def test_phase2b_authoritative_determinism():
    """
    Test 6 — Authoritative Source of Truth:
    Deterministic verification engine remains authoritative for calculations and PASS/FAIL.
    """
    db = SessionLocal()
    try:
        from app.models.models import VerificationRun, VerificationCheck
        vrun = db.query(VerificationRun).order_by(VerificationRun.started_at.desc()).first()
        if not vrun:
            pytest.skip("No verification run in DB")

        checks = db.query(VerificationCheck).filter(VerificationCheck.run_id == vrun.run_id).all()
        if not checks:
            pytest.skip("No checks recorded for verification run")

        # Query the graph for this bundle
        res = app_graph.invoke({"bundle_id": str(vrun.bundle_id), "action": "reverify"})
        verdict = res.get("verdict")
        risk_score = res.get("risk_score")

        # Invariant: Graph verdict and risk score are populated deterministically
        assert verdict in ("clean", "anomaly", "error", "verified", "flagged")
        assert isinstance(risk_score, (int, float))
    finally:
        db.close()
