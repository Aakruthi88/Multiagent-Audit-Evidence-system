"""
Frontend Auth Integration Test Suite - backend/tests/test_frontend_auth_integration.py
--------------------------------------------------------------------------------------
Validates the backend contract used by the frontend authentication layer:
- /api/v1/auth/login with all demo accounts (Auditor, Admin, Second Auditor)
- Invalid credential rejection (401)
- /api/v1/auth/me user profile inspection
- Bearer token authentication lifecycle
- Role separation and bundle access scoping
"""

import pytest
import httpx
from unittest.mock import patch
from app.main import app
from app.db.session import SessionLocal
from app.models.models import AuditBundle
from app.api.v1.auth import init_demo_users


@pytest.fixture(scope="module", autouse=True)
def setup_demo_accounts():
    """Ensure demo accounts are provisioned for testing."""
    db = SessionLocal()
    try:
        init_demo_users(db)
    finally:
        db.close()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def async_client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_login_auditor_success(async_client):
    """Test 1: Auditor demo login returns 200 with JWT and auditor role."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "auditor@audit.local", "password": "auditor123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "auditor@audit.local"
    assert data["user"]["role"] == "auditor"
    assert data["user"]["name"] == "Demo Auditor"


@pytest.mark.anyio
async def test_login_admin_success(async_client):
    """Test 2: Admin demo login returns 200 with JWT and admin role."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@audit.local", "password": "admin123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "admin@audit.local"
    assert data["user"]["role"] == "admin"
    assert data["user"]["name"] == "Audit Administrator"


@pytest.mark.anyio
async def test_login_second_auditor_success(async_client):
    """Test 3: Second Auditor demo login returns 200 with separate identity."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "auditor2@audit.local", "password": "auditor123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "auditor2@audit.local"
    assert data["user"]["role"] == "auditor"
    assert data["user"]["name"] == "Second Auditor"


@pytest.mark.anyio
async def test_login_invalid_password_fails(async_client):
    """Test 4: Invalid password returns 401 with appropriate error detail."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "auditor@audit.local", "password": "wrongpassword999"},
    )
    assert response.status_code == 401
    data = response.json()
    assert "detail" in data
    assert "Incorrect email or password" in data["detail"]


@pytest.mark.anyio
async def test_login_nonexistent_email_fails(async_client):
    """Test 5: Nonexistent user email returns 401."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@audit.local", "password": "anypassword"},
    )
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]


@pytest.mark.anyio
async def test_auth_me_with_valid_token(async_client):
    """Test 6: /auth/me returns current user profile when valid token provided."""
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@audit.local", "password": "admin123"},
    )
    token = login_res.json()["access_token"]

    # Call /auth/me
    me_res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    profile = me_res.json()
    assert profile["email"] == "admin@audit.local"
    assert profile["role"] == "admin"
    assert profile["name"] == "Audit Administrator"


@pytest.mark.anyio
async def test_auth_me_without_token_fails(async_client):
    """Test 7: /auth/me without token returns 401 Unauthorized."""
    response = await async_client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_auth_me_with_invalid_token_fails(async_client):
    """Test 8: /auth/me with bogus or malformed token returns 401."""
    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.jwt.token.string"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_bundle_creation_and_ownership_binding(async_client):
    """Test 9: Creating bundle with auth token sets uploaded_by to authenticated user."""
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "auditor2@audit.local", "password": "auditor123"},
    )
    token = login_res.json()["access_token"]
    user_id = login_res.json()["user"]["user_id"]

    dummy_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    files = {
        "purchase_order": ("po.pdf", dummy_pdf, "application/pdf"),
        "invoice": ("inv.pdf", dummy_pdf, "application/pdf"),
        "grn": ("grn.pdf", dummy_pdf, "application/pdf"),
        "bank_statement": ("bank.pdf", dummy_pdf, "application/pdf"),
    }
    import uuid
    txn_ref = f"TXN-TEST-AUTH-{uuid.uuid4().hex[:8].upper()}"
    data = {"txn_reference": txn_ref}

    with patch("app.api.v1.bundles.process_bundle_task"):
        bundle_res = await async_client.post(
            "/api/v1/bundles",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {token}"},
        )
    assert bundle_res.status_code == 202
    bundle_id = bundle_res.json()["bundle_id"]

    db = SessionLocal()
    try:
        bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
        assert bundle is not None
        assert str(bundle.uploaded_by) == str(user_id)
    finally:
        db.close()
