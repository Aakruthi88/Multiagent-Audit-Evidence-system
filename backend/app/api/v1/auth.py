"""
Authentication API - backend/app/api/v1/auth.py
-----------------------------------------------
Login, profile inspection, and demo user provisioning.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.logging import logger
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.session import get_db
from app.models.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class UserResponse(BaseModel):
    user_id: str
    name: str
    email: str
    role: str


class DemoTokenRequest(BaseModel):
    role: Optional[str] = "auditor"  # "auditor" | "lead"


# ── Endpoints ──────────────────────────────────────────────────────────────────

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

    token = create_access_token(
        subject=user.email,
        role=user.role or "auditor",
        name=user.name
    )

    logger.info(f"[Auth] User '{user.email}' logged in successfully with role '{user.role}'")

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": str(user.user_id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
        }
    }


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Return currently authenticated user profile."""
    return {
        "user_id": str(current_user.user_id),
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
    }


@router.post("/demo-token", response_model=TokenResponse)
def get_demo_token(req: DemoTokenRequest = DemoTokenRequest(), db: Session = Depends(get_db)):
    """
    Demo/Test Helper Endpoint:
    Returns valid JWT access token for demo roles ("auditor" or "lead")
    ensuring automated tests and UI demos can authenticate seamlessly.
    """
    role = (req.role or "auditor").lower().strip()
    if role not in ("auditor", "lead"):
        role = "auditor"

    email = f"{role}@audit.local"
    user = db.query(User).filter(User.email == email).first()
    if not user:
        init_demo_users(db)
        user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(status_code=500, detail="Failed to provision demo user.")

    token = create_access_token(subject=user.email, role=user.role, name=user.name)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": str(user.user_id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
        }
    }


# ── Demo Seed Provisioning ─────────────────────────────────────────────────────

DEMO_USERS = [
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
        "role": "lead",
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
    try:
        db.commit()
        logger.info("[Auth] Demo users initialized in database.")
    except Exception as exc:
        db.rollback()
        logger.warning(f"[Auth] Error initializing demo users: {exc}")
