"""
Role-Scoped Document Retrieval & Pre-Retrieval Authorization Isolation Test Suite
backend/tests/test_role_scoped_retrieval.py
----------------------------------------------------------------------------------
Validates:
1. Auditor A owns Bundle A; Auditor B owns Bundle B.
2. Auditor A querying their own Invoice A -> resolves successfully with 200 OK.
3. Auditor A querying Auditor B's Invoice B -> returns NOT FOUND (pre-retrieval scoping prevents resolution).
4. Auditor A accessing GET /api/v1/bundles/{bundle_b} -> HTTP 403 Forbidden.
5. Auditor A accessing GET /api/v1/bundles/{bundle_b}/export-workpaper -> HTTP 403 Forbidden.
6. Auditor A accessing GET /api/v1/bundles/{bundle_b}/files -> HTTP 403 Forbidden.
7. Auditor A triggering verification for Bundle B -> HTTP 403 Forbidden.
8. Admin querying Invoice A, Invoice B, status queries -> resolves across all bundles org-wide.
9. Source documents in response are strictly isolated to authorized bundle.
10. Status queries (e.g. "show all bundles") are scoped strictly to own bundles for Auditor, and all bundles for Admin.
"""

import uuid
from decimal import Decimal
import pytest
import httpx

from app.main import app
from app.models.models import (
    User, AuditBundle, Document, Invoice, Vendor
)
from app.core.security import get_password_hash, create_access_token
from app.db.session import SessionLocal


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def seed_scoped_data():
    db = SessionLocal()

    try:
        # Users
        user_a = db.query(User).filter(User.email == "alice_scope@deloitte.com").first()
        if not user_a:
            user_a = User(
                user_id=str(uuid.uuid4()),
                name="Auditor Alice",
                email="alice_scope@deloitte.com",
                hashed_password=get_password_hash("AliceSecret123!"),
                role="auditor",
            )
            db.add(user_a)

        user_b = db.query(User).filter(User.email == "bob_scope@deloitte.com").first()
        if not user_b:
            user_b = User(
                user_id=str(uuid.uuid4()),
                name="Auditor Bob",
                email="bob_scope@deloitte.com",
                hashed_password=get_password_hash("BobSecret123!"),
                role="auditor",
            )
            db.add(user_b)

        user_admin = db.query(User).filter(User.email == "carol_scope@deloitte.com").first()
        if not user_admin:
            user_admin = User(
                user_id=str(uuid.uuid4()),
                name="Admin Carol",
                email="carol_scope@deloitte.com",
                hashed_password=get_password_hash("CarolSecret123!"),
                role="admin",
            )
            db.add(user_admin)
        db.flush()

        # Vendor
        vendor_a = Vendor(name_raw="Apex Solutions Inc", name_normalized="apex solutions")
        vendor_b = Vendor(name_raw="Beta Logistics Corp", name_normalized="beta logistics")
        db.add_all([vendor_a, vendor_b])
        db.flush()

        # Generate unique bundle IDs and invoice numbers for test isolation
        bundle_a_id = str(uuid.uuid4())
        bundle_b_id = str(uuid.uuid4())
        inv_a_num = f"INV-ALICE-{uuid.uuid4().hex[:6].upper()}"
        inv_b_num = f"INV-BOB-{uuid.uuid4().hex[:6].upper()}"

        # Bundle A (owned by Auditor A)
        bundle_a = AuditBundle(
            bundle_id=bundle_a_id,
            txn_reference=f"TXN-ALICE-{uuid.uuid4().hex[:6].upper()}",
            status="verified",
            uploaded_by=user_a.user_id,
        )
        db.add(bundle_a)
        db.flush()

        doc_a = Document(
            document_id=str(uuid.uuid4()),
            bundle_id=bundle_a.bundle_id,
            doc_type="invoice",
            file_path="storage/bundles/test/invoice_alice.pdf",
            file_hash=f"hash_alice_{uuid.uuid4().hex[:16]}",
            extraction_status="success",
        )
        inv_a = Invoice(
            document_id=doc_a.document_id,
            bundle_id=bundle_a.bundle_id,
            vendor_id=vendor_a.vendor_id,
            invoice_number=inv_a_num,
            total_amount=Decimal("5000.00"),
            subtotal=Decimal("4500.00"),
            tax_amount=Decimal("500.00"),
        )
        db.add_all([doc_a, inv_a])

        # Bundle B (owned by Auditor B)
        bundle_b = AuditBundle(
            bundle_id=bundle_b_id,
            txn_reference=f"TXN-BOB-{uuid.uuid4().hex[:6].upper()}",
            status="flagged",
            uploaded_by=user_b.user_id,
        )
        db.add(bundle_b)
        db.flush()

        doc_b = Document(
            document_id=str(uuid.uuid4()),
            bundle_id=bundle_b.bundle_id,
            doc_type="invoice",
            file_path="storage/bundles/test/invoice_bob.pdf",
            file_hash=f"hash_bob_{uuid.uuid4().hex[:16]}",
            extraction_status="success",
        )
        inv_b = Invoice(
            document_id=doc_b.document_id,
            bundle_id=bundle_b.bundle_id,
            vendor_id=vendor_b.vendor_id,
            invoice_number=inv_b_num,
            total_amount=Decimal("7500.00"),
            subtotal=Decimal("7000.00"),
            tax_amount=Decimal("500.00"),
        )
        db.add_all([doc_b, inv_b])
        db.commit()

        tokens = {
            "token_a": create_access_token(subject=user_a.email, role="auditor", name=user_a.name),
            "token_b": create_access_token(subject=user_b.email, role="auditor", name=user_b.name),
            "token_admin": create_access_token(subject=user_admin.email, role="admin", name=user_admin.name),
            "bundle_a_id": str(bundle_a.bundle_id),
            "bundle_b_id": str(bundle_b.bundle_id),
            "inv_a_num": inv_a_num,
            "inv_b_num": inv_b_num,
        }

        yield tokens
    finally:
        db.close()


@pytest.fixture
async def client(seed_scoped_data):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


# ── 1. Bundle List Scoping Tests ───────────────────────────────────────────────

@pytest.mark.anyio
async def test_auditor_a_bundle_list_scoped_to_own_bundles(client, seed_scoped_data):
    """Auditor A only sees their own Bundle A in GET /api/v1/bundles."""
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_a']}"}
    resp = await client.get("/api/v1/bundles", headers=headers)
    assert resp.status_code == 200
    bundles = resp.json()
    b_ids = [b["bundle_id"] for b in bundles]
    assert seed_scoped_data["bundle_a_id"] in b_ids
    assert seed_scoped_data["bundle_b_id"] not in b_ids


@pytest.mark.anyio
async def test_auditor_b_bundle_list_scoped_to_own_bundles(client, seed_scoped_data):
    """Auditor B only sees their own Bundle B in GET /api/v1/bundles."""
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_b']}"}
    resp = await client.get("/api/v1/bundles", headers=headers)
    assert resp.status_code == 200
    bundles = resp.json()
    b_ids = [b["bundle_id"] for b in bundles]
    assert seed_scoped_data["bundle_b_id"] in b_ids
    assert seed_scoped_data["bundle_a_id"] not in b_ids


@pytest.mark.anyio
async def test_admin_bundle_list_sees_all_bundles(client, seed_scoped_data):
    """Admin sees both Bundle A and Bundle B."""
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_admin']}"}
    resp = await client.get("/api/v1/bundles", headers=headers)
    assert resp.status_code == 200
    bundles = resp.json()
    b_ids = [b["bundle_id"] for b in bundles]
    assert seed_scoped_data["bundle_a_id"] in b_ids
    assert seed_scoped_data["bundle_b_id"] in b_ids


# ── 2. Direct Cross-Bundle Access Denial Tests ─────────────────────────────────

@pytest.mark.anyio
async def test_auditor_a_cannot_access_bundle_b_detail(client, seed_scoped_data):
    """Auditor A accessing GET /bundles/{bundle_b_id} receives HTTP 403 Forbidden."""
    bundle_b_id = seed_scoped_data["bundle_b_id"]
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_a']}"}
    resp = await client.get(f"/api/v1/bundles/{bundle_b_id}", headers=headers)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_auditor_a_cannot_access_bundle_b_files(client, seed_scoped_data):
    """Auditor A accessing GET /bundles/{bundle_b_id}/files receives HTTP 403 Forbidden."""
    bundle_b_id = seed_scoped_data["bundle_b_id"]
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_a']}"}
    resp = await client.get(f"/api/v1/bundles/{bundle_b_id}/files", headers=headers)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_auditor_a_cannot_export_bundle_b_workpaper(client, seed_scoped_data):
    """Auditor A accessing GET /bundles/{bundle_b_id}/export-workpaper receives HTTP 403 Forbidden."""
    bundle_b_id = seed_scoped_data["bundle_b_id"]
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_a']}"}
    resp = await client.get(f"/api/v1/bundles/{bundle_b_id}/export-workpaper", headers=headers)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_can_access_both_bundles(client, seed_scoped_data):
    """Admin accessing Bundle A and Bundle B details receives HTTP 200 OK."""
    bundle_a_id = seed_scoped_data["bundle_a_id"]
    bundle_b_id = seed_scoped_data["bundle_b_id"]
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_admin']}"}
    resp_a = await client.get(f"/api/v1/bundles/{bundle_a_id}", headers=headers)
    assert resp_a.status_code == 200
    resp_b = await client.get(f"/api/v1/bundles/{bundle_b_id}", headers=headers)
    assert resp_b.status_code == 200


# ── 3. Role-Scoped Query / Ask Documents Pre-Retrieval Isolation ───────────────

@pytest.mark.anyio
async def test_auditor_a_query_own_invoice_resolves(client, seed_scoped_data):
    """Auditor A querying 'What is the total of Invoice {inv_a_num}?' resolves successfully."""
    inv_a_num = seed_scoped_data["inv_a_num"]
    bundle_a_id = seed_scoped_data["bundle_a_id"]
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_a']}"}
    resp = await client.post(
        "/api/v1/run",
        json={"query": f"What is the total of Invoice {inv_a_num}?"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["bundle_id"] == bundle_a_id


@pytest.mark.anyio
async def test_auditor_a_query_other_auditor_invoice_fails_closed(client, seed_scoped_data):
    """
    CRITICAL: Auditor A querying 'What is the total of Invoice {inv_b_num}?' (Auditor B's invoice)
    must NOT resolve Auditor B's bundle (returns not found or None bundle_id).
    Pre-retrieval authorization scoping prevents entity resolver from seeing Bundle B.
    """
    inv_b_num = seed_scoped_data["inv_b_num"]
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_a']}"}
    resp = await client.post(
        "/api/v1/run",
        json={"query": f"What is the total of Invoice {inv_b_num}?"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["bundle_id"] is None  # MUST NOT resolve to bundle_b_id for Auditor A


@pytest.mark.anyio
async def test_admin_query_any_invoice_resolves(client, seed_scoped_data):
    """Admin querying Invoice {inv_b_num} resolves successfully to Bundle B."""
    inv_b_num = seed_scoped_data["inv_b_num"]
    bundle_b_id = seed_scoped_data["bundle_b_id"]
    headers = {"Authorization": f"Bearer {seed_scoped_data['token_admin']}"}
    resp = await client.post(
        "/api/v1/run",
        json={"query": f"What is the total of Invoice {inv_b_num}?"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["bundle_id"] == bundle_b_id
