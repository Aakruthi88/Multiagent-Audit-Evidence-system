import uuid
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.db.session import SessionLocal
from app.models.models import User, AuditBundle, Document, Invoice, Vendor, VerificationRun, VerificationCheck

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def auth_auditor():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo_auditor_dashboard@audit.local").first()
        if not user:
            user = User(
                user_id=str(uuid.uuid4()),
                name="Dashboard Auditor",
                email="demo_auditor_dashboard@audit.local",
                hashed_password=get_password_hash("Password123!"),
                role="admin",
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        token = create_access_token(subject=user.email, role=user.role)
        return {"user": user, "token": token, "headers": {"Authorization": f"Bearer {token}"}}
    finally:
        db.close()

@pytest.mark.anyio
async def test_dashboard_bundle_enrichment_and_pdf_retrieval(auth_auditor):
    """
    Verify:
    1. GET /api/v1/bundles returns vendor_name, risk_score, overall_status, documents.
    2. GET /api/v1/bundles/{bundle_id}/files/bank_statement.pdf resolves to bank_statement_*.pdf
    3. GET /api/v1/bundles/metrics/impact returns real DB verification check numbers.
    """
    headers = auth_auditor["headers"]
    token = auth_auditor["token"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test bundle list enrichment
        res = await client.get("/api/v1/bundles", headers=headers)
        assert res.status_code == 200, f"List bundles failed: {res.text}"
        bundles = res.json()
        assert len(bundles) > 0, "Expected existing audit bundles"

        # Check fields on each bundle
        first_bundle = bundles[0]
        assert "vendor_name" in first_bundle
        assert "risk_score" in first_bundle
        assert "overall_status" in first_bundle
        assert "documents" in first_bundle

        # 2. Test metrics endpoint
        metrics_res = await client.get("/api/v1/bundles/metrics/impact", headers=headers)
        assert metrics_res.status_code == 200
        metrics = metrics_res.json()
        assert "checks_passed" in metrics
        assert "checks_failed" in metrics
        assert "checks_warning" in metrics
        assert isinstance(metrics["checks_passed"], int)

        # 3. Test PDF file retrieval with candidate resolution (e.g. bank_statement.pdf)
        # Find a bundle that has files or create sample files for bundle_id
        bundle_id = first_bundle["bundle_id"]
        bundle_dir = settings.STORAGE_DIR / "bundles" / str(bundle_id)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        sample_pdf = bundle_dir / "bank_statement_bank_statement.pdf"
        if not sample_pdf.exists():
            sample_pdf.write_bytes(b"%PDF-1.4 Mock PDF Content")

        pdf_res = await client.get(f"/api/v1/bundles/{bundle_id}/files/bank_statement.pdf", headers=headers)
        assert pdf_res.status_code == 200, f"Failed resolving bank_statement.pdf for bundle {bundle_id}: {pdf_res.text}"
        assert pdf_res.headers.get("content-type") == "application/pdf"

        # 4. Test with query param ?token=
        pdf_token_res = await client.get(f"/api/v1/bundles/{bundle_id}/files/bank_statement.pdf?token={token}")
        assert pdf_token_res.status_code == 200
        assert pdf_token_res.headers.get("content-type") == "application/pdf"

        # 5. Test genuinely non-existent file returns 404
        bad_pdf_res = await client.get(f"/api/v1/bundles/{bundle_id}/files/non_existent_doc_12345.pdf", headers=headers)
        assert bad_pdf_res.status_code == 404
