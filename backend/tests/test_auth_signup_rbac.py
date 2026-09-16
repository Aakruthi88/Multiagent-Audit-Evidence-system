"""
Auth & Signup RBAC Test Suite - backend/tests/test_auth_signup_rbac.py
----------------------------------------------------------------------
Validates:
1. Signup succeeds and assigns role 'auditor'.
2. Client-supplied role (e.g. 'admin') in signup is ignored/rejected -> always 'auditor'.
3. Duplicate email registration fails with HTTP 400.
4. Missing required fields or password mismatch fails with HTTP 400/422.
5. Short password (< 6 chars) fails with HTTP 400.
6. Login succeeds for Auditor with valid credentials -> returns JWT token + role 'auditor'.
7. Login succeeds for Admin with valid credentials -> returns JWT token + role 'admin'.
8. Invalid password fails with HTTP 401.
9. Nonexistent email fails with HTTP 401.
10. Unauthenticated access to protected endpoint fails with HTTP 401.
11. Corrupted/invalid Bearer token fails with HTTP 401.
12. Auditor accessing Admin-only /api/v1/auth/users fails with HTTP 403 Forbidden.
13. Admin accessing Admin-only /api/v1/auth/users succeeds with HTTP 200 OK.
"""

import uuid
import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.models.models import User
from app.core.security import get_password_hash, create_access_token

# In-memory test SQLite DB
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # Seed Admin and Auditor test users
    admin_user = User(
        user_id=str(uuid.uuid4()),
        name="Chief Admin",
        email="admin_test@deloitte.com",
        hashed_password=get_password_hash("AdminPass123!"),
        role="admin",
    )
    auditor_user = User(
        user_id=str(uuid.uuid4()),
        name="Auditor Alice",
        email="alice_test@deloitte.com",
        hashed_password=get_password_hash("AuditorPass123!"),
        role="auditor",
    )
    db.add_all([admin_user, auditor_user])
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


# ── 1. Signup Tests ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_signup_success(client):
    """Test standard signup flow with valid credentials -> role is auditor."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Bob Test Auditor",
            "email": "bob_auditor@deloitte.com",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Bob Test Auditor"
    assert data["email"] == "bob_auditor@deloitte.com"
    assert data["role"] == "auditor"
    assert "user_id" in data


@pytest.mark.anyio
async def test_signup_rejects_client_supplied_admin_role(client):
    """Critical test: backend ignores/overrides client-supplied 'role: admin' and assigns 'auditor'."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Attacker Trying Admin",
            "email": "attacker@deloitte.com",
            "password": "AttackPassword123!",
            "confirm_password": "AttackPassword123!",
            "role": "admin",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["role"] == "auditor"  # Must NEVER be admin


@pytest.mark.anyio
async def test_signup_duplicate_email_rejected(client):
    """Duplicate email registration must fail with HTTP 400."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Duplicate Bob",
            "email": "bob_auditor@deloitte.com",
            "password": "AnotherPassword123!",
            "confirm_password": "AnotherPassword123!",
        },
    )
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_signup_password_mismatch_rejected(client):
    """Mismatched password confirmation must fail with HTTP 400."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Mismatch User",
            "email": "mismatch@deloitte.com",
            "password": "Password123!",
            "confirm_password": "DifferentPassword123!",
        },
    )
    assert resp.status_code == 400
    assert "do not match" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_signup_short_password_rejected(client):
    """Password shorter than 6 characters must fail with HTTP 400."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Short Pass User",
            "email": "shortpass@deloitte.com",
            "password": "123",
            "confirm_password": "123",
        },
    )
    assert resp.status_code == 400
    assert "at least 6 characters" in resp.json()["detail"].lower()


# ── 2. Login & Token Lifecycle Tests ──────────────────────────────────────────

@pytest.mark.anyio
async def test_login_auditor_success(client):
    """Auditor login returns JWT with role 'auditor'."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice_test@deloitte.com", "password": "AuditorPass123!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["role"] == "auditor"
    assert data["user"]["email"] == "alice_test@deloitte.com"


@pytest.mark.anyio
async def test_login_admin_success(client):
    """Admin login returns JWT with role 'admin'."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_test@deloitte.com", "password": "AdminPass123!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["role"] == "admin"


@pytest.mark.anyio
async def test_login_invalid_password_rejected(client):
    """Incorrect password returns HTTP 401."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice_test@deloitte.com", "password": "WrongPassword!"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_login_nonexistent_email_rejected(client):
    """Nonexistent email returns HTTP 401."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@deloitte.com", "password": "Password123!"},
    )
    assert resp.status_code == 401


# ── 3. Route Protection & RBAC Guard Tests ────────────────────────────────────

@pytest.mark.anyio
async def test_protected_endpoint_without_token_rejected(client):
    """Unauthenticated request to protected endpoint returns HTTP 401."""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_protected_endpoint_with_invalid_token_rejected(client):
    """Corrupted Bearer token returns HTTP 401."""
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.corrupted.token"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_auditor_access_to_admin_users_endpoint_forbidden(client):
    """Auditor trying to access Admin-only /api/v1/auth/users returns HTTP 403 Forbidden."""
    auditor_token = create_access_token(subject="alice_test@deloitte.com", role="auditor")
    resp = await client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_access_to_admin_users_endpoint_allowed(client):
    """Admin accessing /api/v1/auth/users returns HTTP 200 with list of users."""
    admin_token = create_access_token(subject="admin_test@deloitte.com", role="admin")
    resp = await client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    users_list = resp.json()
    assert isinstance(users_list, list)
    assert len(users_list) >= 2
    emails = [u["email"] for u in users_list]
    assert "admin_test@deloitte.com" in emails
    assert "alice_test@deloitte.com" in emails
