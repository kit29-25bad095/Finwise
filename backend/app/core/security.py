import bcrypt
import hashlib
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union
from jose import jwt, JWTError

from app.core.config import settings


class TokenRevocationStore:
    """
    Thread-safe in-memory store for revoked JWTs (token blacklisting).
    Tracks revoked jti (JWT ID) or token digests until token expiration,
    preventing memory leaks by automatically sweeping expired tokens.
    """
    _lock = threading.Lock()
    _revoked_jtis: Dict[str, float] = {}

    @classmethod
    def revoke_token(cls, token: str) -> bool:
        """Revokes a JWT by recording its jti or hash until its expiration timestamp."""
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": False}
            )
            jti = payload.get("jti")
            exp = float(payload.get("exp", 0))
            if not jti:
                jti = hashlib.sha256(token.encode("utf-8")).hexdigest()
            with cls._lock:
                cls._revoked_jtis[jti] = exp
            return True
        except Exception:
            return False

    @classmethod
    def revoke_jti(cls, jti: str, exp: Optional[float] = None) -> None:
        default_exp = datetime.now(timezone.utc).timestamp() + (settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
        with cls._lock:
            cls._revoked_jtis[jti] = exp if exp is not None else default_exp

    @classmethod
    def is_token_revoked(cls, token: str) -> bool:
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": False}
            )
            jti = payload.get("jti")
            if not jti:
                jti = hashlib.sha256(token.encode("utf-8")).hexdigest()
            with cls._lock:
                cls._cleanup()
                return jti in cls._revoked_jtis
        except Exception:
            return False

    @classmethod
    def is_jti_revoked(cls, jti: str) -> bool:
        with cls._lock:
            cls._cleanup()
            return jti in cls._revoked_jtis

    @classmethod
    def _cleanup(cls) -> None:
        now = datetime.now(timezone.utc).timestamp()
        expired = [jti for jti, exp in cls._revoked_jtis.items() if exp and exp < now]
        for jti in expired:
            del cls._revoked_jtis[jti]

    @classmethod
    def reset(cls) -> None:
        """Resets all revoked token state (used in test isolation)."""
        with cls._lock:
            cls._revoked_jtis.clear()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def create_access_token(
    subject: Union[str, Any],
    tenant_id: Optional[str] = None,
    role: Optional[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: Dict[str, Any] = {
        "exp": expire,
        "iat": now,
        "sub": str(subject),
        "type": "access",
        "jti": uuid.uuid4().hex
    }
    if tenant_id:
        to_encode["tenant_id"] = str(tenant_id)
    if role:
        to_encode["role"] = str(role)

    encoded_jwt = jwt.encode(
        to_encode, 
        settings.SECRET_KEY, 
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(
    subject: Union[str, Any],
    tenant_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode: Dict[str, Any] = {
        "exp": expire,
        "iat": now,
        "sub": str(subject),
        "type": "refresh",
        "jti": uuid.uuid4().hex
    }
    if tenant_id:
        to_encode["tenant_id"] = str(tenant_id)

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    if TokenRevocationStore.is_token_revoked(token):
        return None
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        if payload.get("type") and payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    if TokenRevocationStore.is_token_revoked(token):
        return None
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None

