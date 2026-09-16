"""
Authentication API - backend/app/api/v1/auth.py
-----------------------------------------------
Login, profile inspection, and demo user provisioning.
"""

import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.logging import logger
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.session import get_db
from app.models.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    confirm_password: Optional[str] = None
    password_confirm: Optional[str] = None
    role: Optional[str] = None  # Intentionally ignored by backend — always set to 'auditor'


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class UserResponse(BaseModel):
    user_id: str
    name: str
    email: str
    role: str


class UserListItem(BaseModel):
    user_id: str
    name: str
    email: str
    role: str
    created_at: Optional[Any] = None


class DemoTokenRequest(BaseModel):
    role: Optional[str] = "auditor"  # "auditor" | "admin" | "lead"


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    """
    Register a new user account.
    - Validates required fields, email format, and password length/match.
    - CRITICAL: Always assigns role = 'auditor'. Ignores or rejects any client-supplied role.
    - Rejects duplicate email addresses with HTTP 400.
    """
    name_clean = req.name.strip()
    if not name_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full Name is required."
        )

    email_clean = req.email.strip().lower()
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    if not re.match(email_regex, email_clean):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a valid corporate email address."
        )

    # Validate password
    password = req.password or ""
    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long."
        )

    expected_confirm = req.confirm_password if req.confirm_password is not None else req.password_confirm
    if expected_confirm is not None and expected_confirm != password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match."
        )

    # Check for duplicate email
    existing_user = db.query(User).filter(User.email == email_clean).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An account with email '{email_clean}' already exists."
        )

    # Enforce strictly AUDITOR role — never trust client input
    user = User(
        name=name_clean,
        email=email_clean,
        hashed_password=get_password_hash(password),
        role="auditor",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"[Auth] New auditor registered successfully: '{user.email}' (id: {user.user_id})")

    return {
        "user_id": str(user.user_id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
    }


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user with email and password, returning JWT access token."""
    email_clean = req.email.strip().lower()
    user = db.query(User).filter(User.email == email_clean).first()
    if not user or not verify_password(req.password, user.hashed_password):
        logger.warning(f"[Auth] Failed login attempt for email: '{email_clean}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_role = (user.role or "auditor").lower().strip()
    # Normalize legacy 'lead' to 'admin'
    if user_role == "lead":
        user_role = "admin"

    token = create_access_token(
        subject=user.email,
        role=user_role,
        name=user.name
    )

    logger.info(f"[Auth] User '{user.email}' logged in successfully with role '{user_role}'")

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": str(user.user_id),
            "email": user.email,
            "name": user.name,
            "role": user_role,
        }
    }


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Return currently authenticated user profile."""
    user_role = (current_user.role or "auditor").lower().strip()
    if user_role == "lead":
        user_role = "admin"

    return {
        "user_id": str(current_user.user_id),
        "name": current_user.name,
        "email": current_user.email,
        "role": user_role,
    }


@router.get("/users", response_model=List[UserListItem])
def list_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Admin-only User Management:
    Returns list of all registered auditors and administrators.
    """
    users = db.query(User).order_by(User.name.asc()).all()
    results = []
    for u in users:
        r = (u.role or "auditor").lower().strip()
        if r == "lead":
            r = "admin"
        results.append({
            "user_id": str(u.user_id),
            "name": u.name,
            "email": u.email,
            "role": r,
            "created_at": None,
        })
    return results


@router.post("/demo-token", response_model=TokenResponse)
def get_demo_token(req: DemoTokenRequest = DemoTokenRequest(), db: Session = Depends(get_db)):
    """
    Demo/Test Helper Endpoint:
    Returns valid JWT access token for demo roles ("auditor" or "admin").
    """
    role = (req.role or "auditor").lower().strip()
    if role not in ("auditor", "admin", "lead"):
        role = "auditor"

    email = f"{role}@audit.local"
    user = db.query(User).filter(User.email == email).first()
    if not user:
        init_demo_users(db)
        user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(status_code=500, detail="Failed to provision demo user.")

    canonical_role = "admin" if (user.role or "").lower() in ("admin", "lead") else "auditor"
    token = create_access_token(subject=user.email, role=canonical_role, name=user.name)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": str(user.user_id),
            "email": user.email,
            "name": user.name,
            "role": canonical_role,
        }
    }


# ── Demo Seed Provisioning ─────────────────────────────────────────────────────

DEMO_USERS = [
    {
        "name": "Audit Administrator",
        "email": "admin@audit.local",
        "password": "admin123",
        "role": "admin",
    },
    {
        "name": "Demo Auditor",
        "email": "auditor@audit.local",
        "password": "auditor123",
        "role": "auditor",
    },
    {
        "name": "Demo Lead Auditor",
        "email": "lead@audit.local",
        "password": "lead123",
        "role": "admin",
    },
    {
        "name": "Second Auditor",
        "email": "auditor2@audit.local",
        "password": "auditor123",
        "role": "auditor",
    },
]


def init_demo_users(db: Session) -> None:
    """Ensure demo user accounts exist with hashed passwords."""
    for udata in DEMO_USERS:
        existing = db.query(User).filter(User.email == udata["email"]).first()
        if not existing:
            user = User(
                name=udata["name"],
                email=udata["email"],
                hashed_password=get_password_hash(udata["password"]),
                role=udata["role"],
            )
            db.add(user)
        else:
            # Upgrade existing lead to admin if needed
            if existing.email in ("admin@audit.local", "lead@audit.local") and existing.role != "admin":
                existing.role = "admin"
                db.add(existing)

    try:
        db.commit()
        logger.info("[Auth] Demo users initialized in database.")
    except Exception as exc:
        db.rollback()
        logger.warning(f"[Auth] Error initializing demo users: {exc}")

