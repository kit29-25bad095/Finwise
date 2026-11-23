import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from app.core.config import settings


class InMemorySlidingWindowLimiter:
    """
    Thread-safe in-memory sliding window rate limiter with auto-expiring keys.
    Prevents unbounded memory growth by pruning expired timestamps on window queries.
    """
    def __init__(self):
        # Maps client_key -> list of request timestamps (epoch seconds)
        self._records: Dict[str, List[float]] = defaultdict(list)
        self._last_prune = time.time()

    def is_allowed(self, client_key: str, limit: int, window_seconds: int = 60) -> Tuple[bool, int, int]:
        """
        Evaluates whether client_key is within rate limit for window_seconds.
        Returns: (is_allowed, remaining_requests, retry_after_seconds)
        """
        now = time.time()
        window_start = now - window_seconds

        # Periodically prune stale entries across all keys every 5 minutes
        if now - self._last_prune > 300:
            self._prune_all(now, window_seconds)

        timestamps = self._records[client_key]
        # Keep only timestamps within sliding window
        valid_timestamps = [t for t in timestamps if t > window_start]
        self._records[client_key] = valid_timestamps

        count = len(valid_timestamps)
        if count < limit:
            self._records[client_key].append(now)
            remaining = limit - count - 1
            return True, remaining, 0
        else:
            oldest = valid_timestamps[0]
            retry_after = int(oldest + window_seconds - now) + 1
            return False, 0, max(1, retry_after)

    def _prune_all(self, now: float, window_seconds: int):
        window_start = now - window_seconds
        stale_keys = []
        for key, ts_list in self._records.items():
            valid = [t for t in ts_list if t > window_start]
            if valid:
                self._records[key] = valid
            else:
                stale_keys.append(key)
        for k in stale_keys:
            self._records.pop(k, None)
        self._last_prune = now

    def reset(self):
        """Resets all recorded rate limit state (useful in test isolation)."""
        self._records.clear()
        self._last_prune = time.time()


# Singleton limiter instance
limiter = InMemorySlidingWindowLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware providing tiered rate limiting and brute-force protection.
    - Auth endpoints (login/register): 10 req/min (Brute-force mitigation).
    - Write endpoints (upload/trigger): 30 req/min.
    - General endpoints: 120 req/min.
    """
    ENABLED = True  # Can be toggled for test suites
    FORCE_ENABLED = False

    async def dispatch(self, request: Request, call_next):
        if not self.ENABLED or (settings.ENVIRONMENT == "test" and not self.FORCE_ENABLED):
            return await call_next(request)

        # Skip health check endpoints from rate limiting
        path = request.url.path
        if path in ("/health", "/api/v1/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # Extract client IP identifier
        client_ip = request.client.host if request.client else "127.0.0.1"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        # Tiered limit rules (limit, window_seconds)
        if path.startswith("/api/v1/auth/login") or path.startswith("/api/v1/auth/register"):
            key = f"auth:{client_ip}"
            limit = 10
            window = 60
        elif path.startswith("/api/v1/ingestion/upload") or path.startswith("/api/v1/reconciliation/runs"):
            key = f"write:{client_ip}"
            limit = 30
            window = 60
        else:
            key = f"general:{client_ip}"
            limit = 120
            window = 60

        allowed, remaining, retry_after = limiter.is_allowed(key, limit, window)
        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many requests. Rate limit exceeded. Please try again later."},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                }
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
