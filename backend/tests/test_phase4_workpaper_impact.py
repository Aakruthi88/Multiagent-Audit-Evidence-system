"""
Phase 4 Test Suite: Deterministic Audit Workpaper Export + Business Impact / ROI
-------------------------------------------------------------------------------
Verifies:
1. PDF export succeeds for authorized bundle with valid PDF structure (%PDF-).
2. Auditor cannot export another auditor's bundle (403 Forbidden).
3. Lead Auditor can export any auditor's bundle (200 OK).
4. PDF contains correct bundle information and transaction reference.
5. PDF contains deterministic verification check results and PASS/FAIL counts.
6. PDF contains exceptions and discrepancies with severity.
7. PDF contains only current-bundle source documents (strict isolation).
8. PDF does not leak data from other bundles.
9. PDF includes AI summary section only when actually present in DB.
10. PDF financial values match DB records with exact precision.
11. Business Impact / ROI metrics are calculated from real DB data with transparent assumptions.
12. Nonexistent bundle export returns 404 Not Found.
"""

import io
import uuid
from datetime import datetime, date
from decimal import Decimal
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, get_password_hash
from app.db.session import SessionLocal
from app.main import app
from app.models.models import (
    AuditBundle,
    Document,
    Invoice,
    PurchaseOrder,
    GRN,
    BankStatement,
    BankTransaction,
    Vendor,
    VerificationRun,
    VerificationCheck,
    Discrepancy,
    Report,
    User,
)
from app.services.report_export_service import report_export_service


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def setup_users(client):
    """Seed test users: Auditor 1, Auditor 2, and Lead Auditor."""
    db = SessionLocal()
    try:
        # User 1: Auditor A
        u1 = db.query(User).filter(User.email == "auditor_a_p4@deloitte.com").first()
        if not u1:
            u1 = User(
                name="Auditor Alice",
                email="auditor_a_p4@deloitte.com",
                hashed_password=get_password_hash("AuditSecret123!"),
                role="auditor"
            )
            db.add(u1)

        # User 2: Auditor B
        u2 = db.query(User).filter(User.email == "auditor_b_p4@deloitte.com").first()
        if not u2:
            u2 = User(
                name="Auditor Bob",
                email="auditor_b_p4@deloitte.com",
                hashed_password=get_password_hash("AuditSecret123!"),
                role="auditor"
            )
            db.add(u2)

        # User 3: Lead Auditor
        u3 = db.query(User).filter(User.email == "lead_p4@deloitte.com").first()
        if not u3:
            u3 = User(
                name="Lead Auditor Carol",
                email="lead_p4@deloitte.com",
                hashed_password=get_password_hash("LeadSecret123!"),
                role="lead"
            )
            db.add(u3)

        db.commit()
        db.refresh(u1)
        db.refresh(u2)
        db.refresh(u3)

        tokens = {
            "auditor_a": create_access_token(subject=u1.email, role=u1.role, name=u1.name),
            "auditor_b": create_access_token(subject=u2.email, role=u2.role, name=u2.name),
            "lead": create_access_token(subject=u3.email, role=u3.role, name=u3.name),
            "user_a_id": u1.user_id,
            "user_b_id": u2.user_id,
            "lead_id": u3.user_id,
        }
        return tokens
    finally:
        db.close()


@pytest.fixture(scope="module")
def seed_test_bundles(setup_users):
    """Seed two distinct bundles: one for Auditor A with full data, one for Auditor B."""
    db = SessionLocal()
    try:
        user_a_id = setup_users["user_a_id"]
        user_b_id = setup_users["user_b_id"]

        # Bundle A (Owned by Auditor A)
        txn_ref_a = f"TXN-P4-TEST-A-{uuid.uuid4().hex[:6].upper()}"
        bundle_a = AuditBundle(
            txn_reference=txn_ref_a,
            status="verified",
            uploaded_by=user_a_id,
            created_at=datetime.utcnow()
        )
        db.add(bundle_a)
        db.flush()

        # Vendor A
        vendor_a = Vendor(
            name_raw="Apex Tech Solutions Pvt Ltd",
            name_normalized="apex tech solutions pvt ltd"
        )
        db.add(vendor_a)
        db.flush()

        # Documents A
        doc_po_a = Document(
            bundle_id=bundle_a.bundle_id,
            doc_type="purchase_order",
            file_path=f"storage/bundles/{bundle_a.bundle_id}/purchase_order_100099.pdf",
            file_hash="sha256_hash_po_a_1234567890abcdef1234567890abcdef",
            extraction_status="success",
        )
        doc_inv_a = Document(
            bundle_id=bundle_a.bundle_id,
            doc_type="invoice",
            file_path=f"storage/bundles/{bundle_a.bundle_id}/invoice_200099.pdf",
            file_hash="sha256_hash_inv_a_1234567890abcdef1234567890abcdef",
            extraction_status="success",
        )
        doc_grn_a = Document(
            bundle_id=bundle_a.bundle_id,
            doc_type="grn",
            file_path=f"storage/bundles/{bundle_a.bundle_id}/grn_300099.pdf",
            file_hash="sha256_hash_grn_a_1234567890abcdef1234567890abcdef",
            extraction_status="success",
        )
        doc_bs_a = Document(
            bundle_id=bundle_a.bundle_id,
            doc_type="bank_statement",
            file_path=f"storage/bundles/{bundle_a.bundle_id}/bank_400099.pdf",
            file_hash="sha256_hash_bs_a_1234567890abcdef1234567890abcdef",
            extraction_status="success",
        )
        db.add_all([doc_po_a, doc_inv_a, doc_grn_a, doc_bs_a])
        db.flush()

        # PO A
        po_a = PurchaseOrder(
            document_id=doc_po_a.document_id,
            bundle_id=bundle_a.bundle_id,
            po_number="PO-100099",
            po_date=date(2026, 3, 1),
            vendor_id=vendor_a.vendor_id,
            subtotal=Decimal("50000.00"),
            tax_rate=Decimal("18.00"),
            tax_amount=Decimal("9000.00"),
            total_amount=Decimal("59000.00"),
        )
        # Invoice A
        inv_a = Invoice(
            document_id=doc_inv_a.document_id,
            bundle_id=bundle_a.bundle_id,
            invoice_number="INV-200099",
            invoice_date=date(2026, 3, 5),
            due_date=date(2026, 4, 5),
            po_ref_raw="PO-100099",
            vendor_id=vendor_a.vendor_id,
            subtotal=Decimal("50000.00"),
            tax_rate=Decimal("18.00"),
            tax_amount=Decimal("9000.00"),
            total_amount=Decimal("59000.00"),
        )
        # GRN A
        grn_a = GRN(
            document_id=doc_grn_a.document_id,
            bundle_id=bundle_a.bundle_id,
            grn_number="GRN-300099",
            grn_date=date(2026, 3, 4),
            delivery_note_number="DN-9901",
            po_ref_raw="PO-100099",
            vendor_id=vendor_a.vendor_id,
            total_amount=Decimal("50000.00"),
            received_condition="Good",
        )
        # Bank Statement A
        bs_a = BankStatement(
            document_id=doc_bs_a.document_id,
            bundle_id=bundle_a.bundle_id,
            account_number="HDFC-9988776655",
            statement_date=date(2026, 3, 31),
        )
        db.add_all([po_a, inv_a, grn_a, bs_a])
        db.flush()

        # Bank Txn A
        bt_a = BankTransaction(
            statement_id=bs_a.statement_id,
            txn_date=date(2026, 3, 10),
            description_raw="NEFT/INV-200099/Apex Tech",
            debit_amount=Decimal("59000.00"),
            extracted_ref="NEFT-APEX-9901",
            extracted_invoice_number="INV-200099",
            matched_invoice_id=inv_a.invoice_id,
        )
        db.add(bt_a)

        # Verification Run A
        run_a = VerificationRun(
            bundle_id=bundle_a.bundle_id,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            overall_status="clean",
            overall_risk_score=Decimal("0.0"),
            rules_version="1.0",
        )
        db.add(run_a)
        db.flush()

        # Verification Checks A
        chk1 = VerificationCheck(
            run_id=run_a.run_id,
            bundle_id=bundle_a.bundle_id,
            check_type="po_invoice_total_match",
            status="pass",
            expected_value="59000.00",
            actual_value="59000.00",
            variance=Decimal("0.00"),
            explanation="PO and Invoice totals match within tolerance",
        )
        chk2 = VerificationCheck(
            run_id=run_a.run_id,
            bundle_id=bundle_a.bundle_id,
            check_type="po_grn_amount_match",
            status="pass",
            expected_value="50000.00",
            actual_value="50000.00",
            variance=Decimal("0.00"),
            explanation="GRN pre-tax total matches PO pre-tax subtotal",
        )
        chk3 = VerificationCheck(
            run_id=run_a.run_id,
            bundle_id=bundle_a.bundle_id,
            check_type="payment_amount_match",
            status="pass",
            expected_value="59000.00",
            actual_value="59000.00",
            variance=Decimal("0.00"),
            explanation="Bank debit matches invoice total",
        )
        db.add_all([chk1, chk2, chk3])

        # Report A (with pre-existing AI executive summary)
        rep_a = Report(
            run_id=run_a.run_id,
            format="json",
            content_json={
                "executive_summary": "Clean 4-way match verified. Invoice INV-200099 for Apex Tech Solutions is fully reconciled.",
                "narrative": "Clean 4-way match verified. Invoice INV-200099 for Apex Tech Solutions is fully reconciled.",
                "verdict": "clean"
            },
            generated_at=datetime.utcnow()
        )
        db.add(rep_a)

        # Bundle B (Owned by Auditor B with discrepancy)
        txn_ref_b = f"TXN-P4-TEST-B-{uuid.uuid4().hex[:6].upper()}"
        bundle_b = AuditBundle(
            txn_reference=txn_ref_b,
            status="flagged",
            uploaded_by=user_b_id,
            created_at=datetime.utcnow()
        )
        db.add(bundle_b)
        db.flush()

        doc_inv_b = Document(
            bundle_id=bundle_b.bundle_id,
            doc_type="invoice",
            file_path=f"storage/bundles/{bundle_b.bundle_id}/invoice_secret_b.pdf",
            file_hash="sha256_hash_secret_b_999999",
            extraction_status="success",
        )
        db.add(doc_inv_b)
        db.flush()

        inv_b = Invoice(
            document_id=doc_inv_b.document_id,
            bundle_id=bundle_b.bundle_id,
            invoice_number="INV-SECRET-B-777",
            total_amount=Decimal("150000.00"),
        )
        db.add(inv_b)

        run_b = VerificationRun(
            bundle_id=bundle_b.bundle_id,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            overall_status="flagged",
            overall_risk_score=Decimal("40.0"),
            rules_version="1.0",
        )
        db.add(run_b)
        db.flush()

        chk_b = VerificationCheck(
            run_id=run_b.run_id,
            bundle_id=bundle_b.bundle_id,
            check_type="po_invoice_total_match",
            status="fail",
            expected_value="100000.00",
            actual_value="150000.00",
            variance=Decimal("50000.00"),
            severity="critical",
            explanation="Invoice total exceeds PO total by 50,000",
        )
        db.add(chk_b)
        db.flush()

        disc_b = Discrepancy(
            run_id=run_b.run_id,
            check_id=chk_b.check_id,
            category="amount_mismatch",
            severity="critical",
            description="Invoice total exceeds PO total by ₹50,000.00 (overbill).",
            recommended_action="Obtain approved PO amendment or reject invoice.",
        )
        db.add(disc_b)

        db.commit()

        return {
            "bundle_a_id": str(bundle_a.bundle_id),
            "txn_ref_a": txn_ref_a,
            "bundle_b_id": str(bundle_b.bundle_id),
            "txn_ref_b": txn_ref_b,
        }
    finally:
        db.close()


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Helper to extract raw text from PDF bytes using pypdfium2."""
    pdf = pdfium.PdfDocument(pdf_bytes)
    full_text = []
    for page in pdf:
        textpage = page.get_textpage()
        full_text.append(textpage.get_text_range())
    return "\n".join(full_text)


# ── Test 1: PDF Export Endpoint for Authorized Bundle ──────────────────────────

def test_export_workpaper_success_authorized(client, setup_users, seed_test_bundles):
    """Auditor A exports their own bundle A -> HTTP 200 with valid application/pdf."""
    bundle_id = seed_test_bundles["bundle_a_id"]
    token = setup_users["auditor_a"]

    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(f"/api/v1/bundles/{bundle_id}/export-workpaper", headers=headers)

    assert resp.status_code == 200
    assert "application/pdf" in resp.headers.get("content-type", "")
    assert f"audit_workpaper_{seed_test_bundles['txn_ref_a']}.pdf" in resp.headers.get("content-disposition", "")

    # Validate PDF magic bytes
    assert resp.content.startswith(b"%PDF-")
    assert len(resp.content) > 1000


# ── Test 2: RBAC Isolation - Unauthorized Auditor Access Denied ────────────────

def test_export_workpaper_unauthorized_auditor_denied(client, setup_users, seed_test_bundles):
    """Auditor A attempts to export Auditor B's bundle -> HTTP 403 Forbidden."""
    bundle_b_id = seed_test_bundles["bundle_b_id"]
    token_a = setup_users["auditor_a"]

    headers = {"Authorization": f"Bearer {token_a}"}
    resp = client.get(f"/api/v1/bundles/{bundle_b_id}/export-workpaper", headers=headers)

    assert resp.status_code == 403
    assert "not authorized" in resp.json().get("detail", "").lower()


# ── Test 3: Lead Auditor Supervisory Access ────────────────────────────────────

def test_export_workpaper_lead_auditor_access(client, setup_users, seed_test_bundles):
    """Lead Auditor can export any bundle (including Auditor B's bundle) -> HTTP 200 OK."""
    bundle_b_id = seed_test_bundles["bundle_b_id"]
    token_lead = setup_users["lead"]

    headers = {"Authorization": f"Bearer {token_lead}"}
    resp = client.get(f"/api/v1/bundles/{bundle_b_id}/export-workpaper", headers=headers)

    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF-")


# ── Test 4: PDF Contains Correct Bundle Info & Authoritative Values ─────────────

def test_pdf_contains_correct_bundle_and_financials(client, setup_users, seed_test_bundles):
    """Verify generated PDF contains transaction ref, vendor, and exact financial values."""
    bundle_id = seed_test_bundles["bundle_a_id"]
    token = setup_users["auditor_a"]

    resp = client.get(f"/api/v1/bundles/{bundle_id}/export-workpaper", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    pdf_text = _extract_pdf_text(resp.content)

    # 1. Engagement & Bundle info
    assert seed_test_bundles["txn_ref_a"] in pdf_text
    assert "Apex Tech Solutions Pvt Ltd" in pdf_text
    assert "PO-100099" in pdf_text
    assert "INV-200099" in pdf_text
    assert "GRN-300099" in pdf_text
    assert "HDFC-9988776655" in pdf_text

    # 2. Financial totals: 59,000.00 and 50,000.00
    assert "59,000.00" in pdf_text
    assert "50,000.00" in pdf_text


# ── Test 5: PDF Contains Deterministic Check Results and Verification Matrix ───

def test_pdf_contains_deterministic_checks(client, setup_users, seed_test_bundles):
    """Verify deterministic check matrix is present with PASS badges and explanations."""
    bundle_id = seed_test_bundles["bundle_a_id"]
    token = setup_users["auditor_a"]

    resp = client.get(f"/api/v1/bundles/{bundle_id}/export-workpaper", headers={"Authorization": f"Bearer {token}"})
    pdf_text = _extract_pdf_text(resp.content)

    assert "DETERMINISTIC VERIFICATION MATRIX" in pdf_text
    assert "Po Invoice Total Match" in pdf_text or "po_invoice_total_match" in pdf_text.lower()
    assert "Po Grn Amount Match" in pdf_text or "po_grn_amount_match" in pdf_text.lower()
    assert "Payment Amount Match" in pdf_text or "payment_amount_match" in pdf_text.lower()
    assert "PASS" in pdf_text


# ── Test 6: PDF Contains Exceptions & Discrepancies When Present ───────────────

def test_pdf_contains_exceptions_and_discrepancies(client, setup_users, seed_test_bundles):
    """Verify bundle B PDF contains critical discrepancy findings."""
    bundle_b_id = seed_test_bundles["bundle_b_id"]
    token_lead = setup_users["lead"]

    resp = client.get(f"/api/v1/bundles/{bundle_b_id}/export-workpaper", headers={"Authorization": f"Bearer {token_lead}"})
    assert resp.status_code == 200

    pdf_text = _extract_pdf_text(resp.content)

    assert "EXCEPTIONS & AUDIT FINDINGS" in pdf_text
    assert "Amount Mismatch" in pdf_text or "amount_mismatch" in pdf_text.lower()
    assert "CRITICAL" in pdf_text
    assert "50,000" in pdf_text
    assert "Obtain approved PO amendment" in pdf_text


# ── Test 7: Source Document Hash & Strict Cross-Bundle Data Isolation ───────────

def test_pdf_strict_cross_bundle_isolation(client, setup_users, seed_test_bundles):
    """Bundle A PDF must contain only Bundle A documents and NEVER leak Bundle B data."""
    bundle_a_id = seed_test_bundles["bundle_a_id"]
    token_a = setup_users["auditor_a"]

    resp_a = client.get(f"/api/v1/bundles/{bundle_a_id}/export-workpaper", headers={"Authorization": f"Bearer {token_a}"})
    pdf_text_a = _extract_pdf_text(resp_a.content)

    # Must contain Bundle A hashes and refs
    assert "sha256_hash_po_a" in pdf_text_a
    assert "sha256_hash_inv_a" in pdf_text_a

    # Must NOT contain Bundle B sensitive strings
    assert "INV-SECRET-B-777" not in pdf_text_a
    assert "sha256_hash_secret_b" not in pdf_text_a
    assert seed_test_bundles["txn_ref_b"] not in pdf_text_a


# ── Test 8: AI Summary Clean Separation & Disclaimer ───────────────────────────

def test_pdf_ai_summary_separation_and_disclaimer(client, setup_users, seed_test_bundles):
    """Verify AI executive summary is rendered under dedicated section with audit disclaimer."""
    bundle_a_id = seed_test_bundles["bundle_a_id"]
    token_a = setup_users["auditor_a"]

    resp_a = client.get(f"/api/v1/bundles/{bundle_a_id}/export-workpaper", headers={"Authorization": f"Bearer {token_a}"})
    pdf_text_a = _extract_pdf_text(resp_a.content)

    assert "AI-GENERATED EXPLANATION" in pdf_text_a
    assert "Clean 4-way match verified" in pdf_text_a
    assert "IMPORTANT AUDIT NOTICE" in pdf_text_a
    assert "sole authoritative basis" in pdf_text_a


# ── Test 9: AI Summary Omitted When Absent in DB ───────────────────────────────

def test_pdf_omits_ai_section_when_no_ai_summary(client, setup_users, seed_test_bundles):
    """Bundle B has no AI summary in DB -> AI section is cleanly omitted."""
    bundle_b_id = seed_test_bundles["bundle_b_id"]
    token_lead = setup_users["lead"]

    resp_b = client.get(f"/api/v1/bundles/{bundle_b_id}/export-workpaper", headers={"Authorization": f"Bearer {token_lead}"})
    pdf_text_b = _extract_pdf_text(resp_b.content)

    assert "H. AI-GENERATED EXPLANATION" not in pdf_text_b


# ── Test 10: Direct Service Call Unit Test ─────────────────────────────────────

def test_report_export_service_direct_unit(seed_test_bundles):
    """Unit test generating PDF directly from ReportExportService instance."""
    db = SessionLocal()
    try:
        bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == seed_test_bundles["bundle_a_id"]).first()
        pdf_bytes = report_export_service.generate_workpaper_pdf(db, bundle)

        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b"%PDF-")
        assert len(pdf_bytes) > 2000
    finally:
        db.close()


# ── Test 11: Business Impact & ROI Metrics API Derived from Real DB Data ───────

def test_business_impact_metrics_endpoint(client, setup_users):
    """Verify /api/v1/bundles/metrics/impact calculates real metrics from DB."""
    token_lead = setup_users["lead"]
    headers = {"Authorization": f"Bearer {token_lead}"}

    resp = client.get("/api/v1/bundles/metrics/impact", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Core metrics must be real computed numbers
    assert data["total_bundles_audited"] >= 2
    assert data["total_documents_processed"] >= 4
    assert data["total_verification_checks"] >= 3
    assert data["total_transaction_value_reviewed"] > 0
    assert data["estimated_manual_hours_saved"] >= 0

    # Benchmark assumption transparency
    assumptions = data.get("roi_benchmark_assumptions")
    assert assumptions is not None
    assert assumptions["minutes_per_document_manual_review"] == 15
    assert assumptions["minutes_per_cross_matching_check"] == 2
    assert "benchmark" in assumptions["basis"].lower()


# ── Test 12: Non-Existent Bundle Returns 404 ───────────────────────────────────

def test_export_workpaper_nonexistent_bundle_404(client, setup_users):
    """Requesting export for a nonexistent bundle returns HTTP 404."""
    fake_id = str(uuid.uuid4())
    token_lead = setup_users["lead"]

    resp = client.get(f"/api/v1/bundles/{fake_id}/export-workpaper", headers={"Authorization": f"Bearer {token_lead}"})
    assert resp.status_code == 404
