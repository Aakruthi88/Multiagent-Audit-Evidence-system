"""
Phase 3 Security & Compliance Test Suite
Tests authentication, authorization (RBAC), bundle data isolation,
path traversal prevention, file validation, and CORS security.
"""

import io
import uuid
import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.models import User, AuditBundle
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings

# Shared in-memory SQLite database across all connections
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

AUDITOR_1_ID = str(uuid.uuid4())
AUDITOR_2_ID = str(uuid.uuid4())
LEAD_ID = str(uuid.uuid4())

BUNDLE_1_ID = str(uuid.uuid4())
BUNDLE_2_ID = str(uuid.uuid4())
BUNDLE_LEGACY_ID = str(uuid.uuid4())


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # Seed test users
    u1 = User(
        user_id=AUDITOR_1_ID,
        email="auditor1@audit.local",
        hashed_password=get_password_hash("password123"),
        name="Auditor One",
        role="auditor",
    )
    u2 = User(
        user_id=AUDITOR_2_ID,
        email="auditor2@audit.local",
        hashed_password=get_password_hash("password123"),
        name="Auditor Two",
        role="auditor",
    )
    u_lead = User(
        user_id=LEAD_ID,
        email="lead@audit.local",
        hashed_password=get_password_hash("leadpassword"),
        name="Lead Auditor",
        role="lead",
    )
    db.add_all([u1, u2, u_lead])

    # Seed bundles
    b1 = AuditBundle(
        bundle_id=BUNDLE_1_ID,
        txn_reference="TXN-AUD-001",
        uploaded_by=AUDITOR_1_ID,
        status="verified",
    )
    b2 = AuditBundle(
        bundle_id=BUNDLE_2_ID,
        txn_reference="TXN-AUD-002",
        uploaded_by=AUDITOR_2_ID,
        status="pending",
    )
    b_unassigned = AuditBundle(
        bundle_id=BUNDLE_LEGACY_ID,
        txn_reference="TXN-LEG-001",
        uploaded_by=None,
        status="verified",
    )
    db.add_all([b1, b2, b_unassigned])
    db.commit()

    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
async def client(db_session):
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auditor1_headers():
    token = create_access_token(subject="auditor1@audit.local", role="auditor")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auditor2_headers():
    token = create_access_token(subject="auditor2@audit.local", role="auditor")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def lead_headers():
    token = create_access_token(subject="lead@audit.local", role="lead")
    return {"Authorization": f"Bearer {token}"}


# ── 1. Authentication & Token Tests ──────────────────────────────────────────

@pytest.mark.anyio
async def test_unauthenticated_request_fails(client):
    """Unauthenticated access to protected endpoints must return 401."""
    res = await client.get("/api/v1/bundles")
    assert res.status_code == 401
    assert "Authentication required" in res.json().get("detail", "")

    res = await client.get(f"/api/v1/bundles/{BUNDLE_1_ID}")
    assert res.status_code == 401

    res = await client.post("/api/v1/run", json={"query": "test"})
    assert res.status_code == 401


@pytest.mark.anyio
async def test_auth_login_success(client):
    """Valid credentials return JWT token and user info."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "auditor1@audit.local", "password": "password123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["role"] == "auditor"


@pytest.mark.anyio
async def test_auth_login_invalid_credentials(client):
    """Invalid password returns 401."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "auditor1@audit.local", "password": "wrongpassword"},
    )
    assert res.status_code == 401
    assert "Incorrect email or password" in res.json()["detail"]


@pytest.mark.anyio
async def test_auth_me_endpoint(client, auditor1_headers):
    """GET /auth/me returns current user profile."""
    res = await client.get("/api/v1/auth/me", headers=auditor1_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "auditor1@audit.local"
    assert data["role"] == "auditor"


# ── 2. Bundle Data Isolation & RBAC ───────────────────────────────────────────

@pytest.mark.anyio
async def test_auditor_can_access_own_bundle(client, auditor1_headers):
    """Auditor 1 can access their own bundle."""
    res = await client.get(f"/api/v1/bundles/{BUNDLE_1_ID}", headers=auditor1_headers)
    assert res.status_code == 200
    assert res.json()["bundle_id"] == BUNDLE_1_ID


@pytest.mark.anyio
async def test_auditor_cannot_access_other_user_bundle(client, auditor1_headers):
    """Auditor 1 receives 403 Forbidden when attempting to access Auditor 2's bundle."""
    res = await client.get(f"/api/v1/bundles/{BUNDLE_2_ID}", headers=auditor1_headers)
    assert res.status_code == 403
    assert "Access to this audit bundle is not authorized" in res.json()["detail"]


@pytest.mark.anyio
async def test_auditor_bundle_list_is_scoped(client, auditor1_headers):
    """Auditor 1 only sees their own bundles and unassigned legacy bundles."""
    res = await client.get("/api/v1/bundles", headers=auditor1_headers)
    assert res.status_code == 200
    bundle_ids = [b["bundle_id"] for b in res.json()]
    assert BUNDLE_1_ID in bundle_ids
    assert BUNDLE_LEGACY_ID in bundle_ids
    assert BUNDLE_2_ID not in bundle_ids  # Auditor 2's bundle is excluded!


@pytest.mark.anyio
async def test_lead_can_access_all_bundles(client, lead_headers):
    """Lead auditor has cross-tenant access to all bundles."""
    res = await client.get("/api/v1/bundles", headers=lead_headers)
    assert res.status_code == 200
    bundle_ids = [b["bundle_id"] for b in res.json()]
    assert BUNDLE_1_ID in bundle_ids
    assert BUNDLE_2_ID in bundle_ids
    assert BUNDLE_LEGACY_ID in bundle_ids

    # Lead can fetch specific bundles from any auditor
    res1 = await client.get(f"/api/v1/bundles/{BUNDLE_1_ID}", headers=lead_headers)
    assert res1.status_code == 200
    res2 = await client.get(f"/api/v1/bundles/{BUNDLE_2_ID}", headers=lead_headers)
    assert res2.status_code == 200


@pytest.mark.anyio
async def test_run_endpoint_bundle_isolation(client, auditor1_headers):
    """Auditor 1 cannot execute /run on Auditor 2's bundle."""
    res = await client.post(
        "/api/v1/run",
        headers=auditor1_headers,
        json={"bundle_id": BUNDLE_2_ID, "action": "reverify"},
    )
    assert res.status_code == 403


# ── 3. Document & Path Traversal Security ──────────────────────────────────────

@pytest.mark.anyio
async def test_path_traversal_in_document_download(client, auditor1_headers):
    """Path traversal sequences (.., /, \\) are rejected."""
    # Attempt with .. in filename
    res = await client.get(f"/api/v1/bundles/{BUNDLE_1_ID}/files/..%2f..%2fetc/passwd", headers=auditor1_headers)
    assert res.status_code in (400, 404)

    # Attempt with invalid non-PDF file name format
    res = await client.get(f"/api/v1/bundles/{BUNDLE_1_ID}/files/exploit.exe", headers=auditor1_headers)
    assert res.status_code == 400
    assert "Invalid filename" in res.json()["detail"]


@pytest.mark.anyio
async def test_file_upload_rejects_non_pdf(client, auditor1_headers):
    """Uploading non-PDF files is rejected with 400 Bad Request."""
    file_data = io.BytesIO(b"malicious script content")
    res = await client.post(
        "/api/v1/bundles",
        headers=auditor1_headers,
        data={"txn_reference": "TXN-SEC-TEST-999"},
        files={"purchase_order": ("malicious.exe", file_data, "application/octet-stream")},
    )
    assert res.status_code == 400
    assert "Only PDF documents are allowed" in res.json()["detail"]


# ── 4. CORS & Compliance Configuration ─────────────────────────────────────────

def test_cors_does_not_contain_wildcard():
    """Ensure CORS origins does not allow global wildcard *."""
    for origin in settings.CORS_ORIGINS:
        assert origin != "*", "Wildcard '*' origin detected in CORS configuration!"


@pytest.mark.anyio
async def test_jwt_tampered_token_fails(client):
    """Tampered token is rejected with 401."""
    tampered_headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.fake.signature"}
    res = await client.get("/api/v1/bundles", headers=tampered_headers)
    assert res.status_code == 401
