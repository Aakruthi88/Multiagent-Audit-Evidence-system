"""
Security utilities - backend/app/core/security.py
-------------------------------------------------
Password hashing with bcrypt and JWT token generation/validation.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union
import bcrypt
import jwt

from app.core.config import settings
from app.core.logging import logger


def get_password_hash(password: str) -> str:
    """Hash password using bcrypt."""
    pw_bytes = password.encode("utf-8")[:72]  # bcrypt max length
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        pw_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pw_bytes, hash_bytes)
    except Exception as exc:
        logger.warning(f"[Security] Password verification error: {exc}")
        return False


def create_access_token(
    subject: Union[str, Any],
    role: str = "auditor",
    name: Optional[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Generate signed JWT access token."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "name": name or "",
        "iat": now,
        "exp": expire,
    }

    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate JWT access token. Returns claims dict or None."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except jwt.PyJWTError as exc:
        logger.warning(f"[Security] JWT decode error: {exc}")
        return None
