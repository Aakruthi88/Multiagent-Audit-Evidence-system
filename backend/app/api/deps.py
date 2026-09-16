"""
Authentication and Authorization Dependencies - backend/app/api/deps.py
------------------------------------------------------------------------
Server-side RBAC, JWT validation, and client/bundle isolation guards.
"""

from typing import Any, Callable, List, Optional, Union
from uuid import UUID
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.models import AuditBundle, User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False
)


def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    auth_token: Optional[str] = Query(None, alias="token"),
    db: Session = Depends(get_db)
) -> User:
    """
    Authenticate and return the current user from JWT token.
    Fails closed with HTTP 401 if token is missing, expired, or invalid.
    Accepts token via Authorization: Bearer <token> or query parameter (?token=).
    """
    effective_token = token or auth_token
    if not effective_token:
        # Check Authorization header manually as fallback
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            effective_token = auth_header[7:].strip()

    if not effective_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(effective_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or corrupted authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token claims (missing sub).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Lookup user by email or user_id
    user = db.query(User).filter(User.email == sub).first()
    if not user:
        try:
            user = db.query(User).filter(User.user_id == sub).first()
        except Exception:
            pass

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user no longer exists in system.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(allowed_roles: List[str]) -> Callable:
    """RBAC guard: require user role to be in allowed_roles."""
    allowed_normalized = {r.lower().strip() for r in allowed_roles}

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role = (current_user.role or "auditor").lower().strip()
        if user_role not in allowed_normalized:
            logger.warning(
                f"[RBAC] Access denied for user '{current_user.email}' with role '{user_role}'. Required: {allowed_roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Requires one of roles: {allowed_roles}",
            )
        return current_user

    return role_checker


# Role dependencies
require_auditor = require_role(["auditor", "lead"])
require_lead = require_role(["lead"])


def verify_bundle_access(
    bundle_id: Union[str, UUID],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> AuditBundle:
    """
    Client/Bundle Data Isolation Guard:
    1. Verifies bundle existence (returns 404 if missing).
    2. Enforces ownership:
       - Lead role can access all bundles.
       - Auditor role can ONLY access bundles uploaded by them (or unassigned demo bundles).
       - Denies access with HTTP 403 if bundle is owned by a different user.
    """
    bundle_id_str = str(bundle_id)
    bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id_str).first()
    if not bundle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit bundle '{bundle_id_str}' not found."
        )

    user_role = (current_user.role or "auditor").lower().strip()
    if user_role == "lead":
        return bundle

    # Auditor role check
    if bundle.uploaded_by is not None:
        if str(bundle.uploaded_by) != str(current_user.user_id):
            logger.warning(
                f"[BundleIsolation] User '{current_user.email}' (id: {current_user.user_id}) "
                f"attempted unauthorized access to bundle '{bundle_id_str}' (owned by {bundle.uploaded_by})."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access to this audit bundle is not authorized."
            )

    return bundle
