import bcrypt
import hashlib
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union
from jose import jwt, JWTError
import redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger("finora.security")


class TokenRevocationError(Exception):
    """Raised when token revocation fails in strict fail-secure mode."""
    pass


class TokenRevocationStore:
    """
    Distributed Redis-backed store for revoked JWTs (token blacklisting).
    Stores revoked JWT identifiers (jti) in Redis with automatic TTL expiration
    matching the token's 'exp' claim.

    Guarantees consistent revocation state across multiple application workers,
    processes, and replicas without storing raw JWT tokens.
    """
    _pool: Optional[redis.ConnectionPool] = None
    _redis_client: Optional[redis.Redis] = None
    _lock = threading.Lock()
    _memory_fallback: Dict[str, float] = {}

    @classmethod
    def _get_key_prefix(cls) -> str:
        return getattr(settings, "JWT_REVOCATION_PREFIX", "finora:revoked_token:")

    @classmethod
    def _make_key(cls, jti: str) -> str:
        return f"{cls._get_key_prefix()}{jti}"

    @classmethod
    def get_redis_client(cls) -> Optional[redis.Redis]:
        """Returns or initializes a thread-safe connection-pooled Redis client."""
        if cls._redis_client is not None:
            return cls._redis_client
        with cls._lock:
            if cls._redis_client is not None:
                return cls._redis_client
            try:
                # Normalize localhost to 127.0.0.1 on Windows to eliminate IPv6 timeout
                redis_url = settings.REDIS_URL
                if "localhost" in redis_url:
                    redis_url = redis_url.replace("localhost", "127.0.0.1")
                cls._pool = redis.ConnectionPool.from_url(
                    redis_url,
                    socket_timeout=1.5,
                    socket_connect_timeout=1.5,
                    max_connections=50,
                    decode_responses=True,
                )
                client = redis.Redis(connection_pool=cls._pool)
                client.ping()
                cls._redis_client = client
                return cls._redis_client
            except Exception as e:
                logger.warning("Could not establish connection to Redis (%s): %s", settings.REDIS_URL, e)
                cls._redis_client = None
                cls._pool = None
                return None

    @classmethod
    def set_redis_client(cls, client: Optional[redis.Redis]) -> None:
        """Injects or overrides Redis client (used for testing or dependency injection)."""
        with cls._lock:
            cls._redis_client = client

    @classmethod
    def _calculate_ttl(cls, exp: Optional[float]) -> int:
        now = datetime.now(timezone.utc).timestamp()
        if exp is not None:
            ttl = int(exp - now)
        else:
            ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
        return max(1, ttl)

    @classmethod
    def revoke_token(cls, token: str) -> bool:
        """
        Revokes a JWT by recording its jti (or SHA-256 hash) in Redis.
        Extracts the 'exp' claim to set an automatic Redis key TTL.
        Returns True if revocation was recorded, False otherwise.
        """
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": False}
            )
            jti = payload.get("jti")
            exp = float(payload.get("exp", 0)) if payload.get("exp") else None
            if not jti:
                jti = hashlib.sha256(token.encode("utf-8")).hexdigest()
            return cls.revoke_jti(jti=jti, exp=exp)
        except Exception as e:
            logger.warning("Failed to decode token for revocation: %s", e)
            jti = hashlib.sha256(token.encode("utf-8")).hexdigest()
            return cls.revoke_jti(jti=jti, exp=None)

    @classmethod
    def revoke_jti(cls, jti: str, exp: Optional[float] = None) -> bool:
        """
        Stores a revoked jti in Redis with TTL matching token expiration.
        """
        key = cls._make_key(jti)
        ttl = cls._calculate_ttl(exp)
        revocation_val = datetime.now(timezone.utc).isoformat()

        # Update in-memory fallback for local consistency
        with cls._lock:
            cls._memory_fallback[jti] = exp if exp is not None else (datetime.now(timezone.utc).timestamp() + ttl)

        client = cls.get_redis_client()
        if client is not None:
            try:
                client.set(key, revocation_val, ex=ttl)
                return True
            except RedisError as e:
                logger.error("Failed to store revoked jti in Redis (%s): %s", jti, e)
                if settings.is_production or not settings.WORKER_FALLBACK_SYNC or getattr(settings, "JWT_REVOCATION_FAIL_SECURE", True):
                    raise TokenRevocationError(f"Failed to record token revocation in Redis: {str(e)}")
                return False
        else:
            if settings.is_production or not settings.WORKER_FALLBACK_SYNC or getattr(settings, "JWT_REVOCATION_FAIL_SECURE", True):
                if settings.ENVIRONMENT != "test":
                    raise TokenRevocationError("Redis is unreachable. Cannot record token revocation in secure mode.")
            return True

    @classmethod
    def is_token_revoked(cls, token: str) -> bool:
        """Checks if token's jti is in the revocation store."""
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
            return cls.is_jti_revoked(jti)
        except Exception:
            return True

    @classmethod
    def is_jti_revoked(cls, jti: str) -> bool:
        """
        Checks whether jti exists in Redis.
        Fails secure (returns True) if Redis is unavailable in secure mode.
        """
        if not jti:
            return False

        key = cls._make_key(jti)
        client = cls.get_redis_client()

        if client is not None:
            try:
                exists = client.exists(key)
                if exists:
                    return True
                with cls._lock:
                    cls._cleanup_memory()
                    if jti in cls._memory_fallback:
                        return True
                return False
            except RedisError as e:
                logger.error("Redis connection error during token revocation check for %s: %s", jti, e)
                if settings.is_production or not settings.WORKER_FALLBACK_SYNC or getattr(settings, "JWT_REVOCATION_FAIL_SECURE", True):
                    logger.error("Failing secure: treating token as revoked due to Redis error.")
                    return True
                with cls._lock:
                    cls._cleanup_memory()
                    return jti in cls._memory_fallback
        else:
            if settings.is_production or not settings.WORKER_FALLBACK_SYNC or (getattr(settings, "JWT_REVOCATION_FAIL_SECURE", True) and settings.ENVIRONMENT != "test"):
                logger.error("Token revocation store unreachable (no Redis client). Failing secure.")
                return True
            with cls._lock:
                cls._cleanup_memory()
                return jti in cls._memory_fallback

    @classmethod
    def _cleanup_memory(cls) -> None:
        now = datetime.now(timezone.utc).timestamp()
        expired = [jti for jti, exp in cls._memory_fallback.items() if exp and exp < now]
        for jti in expired:
            del cls._memory_fallback[jti]

    @classmethod
    def reset(cls) -> None:
        """Resets revocation state across memory and Redis (used for test isolation)."""
        with cls._lock:
            cls._memory_fallback.clear()
        client = cls.get_redis_client()
        if client is not None:
            try:
                cursor = 0
                prefix = cls._get_key_prefix()
                while True:
                    cursor, keys = client.scan(cursor=cursor, match=f"{prefix}*", count=100)
                    if keys:
                        client.delete(*keys)
                    if cursor == 0 or cursor == "0":
                        break
            except Exception as e:
                logger.warning("Could not flush Redis revocation keys during reset: %s", e)


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
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        if payload.get("type") and payload.get("type") != "access":
            return None
        jti = payload.get("jti") or hashlib.sha256(token.encode("utf-8")).hexdigest()
        if TokenRevocationStore.is_jti_revoked(jti):
            return None
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        if payload.get("type") != "refresh":
            return None
        jti = payload.get("jti") or hashlib.sha256(token.encode("utf-8")).hexdigest()
        if TokenRevocationStore.is_jti_revoked(jti):
            return None
        return payload
    except JWTError:
        return None
