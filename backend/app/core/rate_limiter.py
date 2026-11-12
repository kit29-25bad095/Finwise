import time
import threading
from typing import Dict, Tuple
from fastapi import Request, HTTPException, status


class InMemoryRateLimiter:
    """
    Thread-safe in-memory sliding-window rate limiter for sensitive endpoints
    (e.g., authentication, registration, password attempts).
    Tracks requests per client IP and enforces brute-force lockouts.
    """

    def __init__(
        self,
        requests_limit: int = 10,
        window_seconds: int = 60,
        lockout_threshold: int = 5,
        lockout_duration_seconds: int = 60
    ):
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.lockout_threshold = lockout_threshold
        self.lockout_duration_seconds = lockout_duration_seconds
        self._lock = threading.Lock()
        # client_ip -> [timestamps]
        self._requests: Dict[str, list] = {}
        # client_ip -> (failure_count, lockout_until_timestamp)
        self._failures: Dict[str, Tuple[int, float]] = {}

    def _get_client_ip(self, request: Request) -> str:
        # Respect X-Forwarded-For if behind a reverse proxy (take first IP)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "127.0.0.1"

    def check_rate_limit(self, request: Request) -> None:
        ip = self._get_client_ip(request)
        now = time.time()

        with self._lock:
            # Check if currently locked out
            if ip in self._failures:
                fail_count, lockout_until = self._failures[ip]
                if now < lockout_until:
                    retry_after = int(lockout_until - now) + 1
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Too many failed attempts. Temporary lockout active. Try again in {retry_after} seconds.",
                        headers={"Retry-After": str(retry_after)}
                    )
                elif now >= lockout_until and lockout_until > 0:
                    # Lockout expired, reset failure counter
                    del self._failures[ip]

            # Prune expired requests
            if ip not in self._requests:
                self._requests[ip] = []

            cutoff = now - self.window_seconds
            self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]

            if len(self._requests[ip]) >= self.requests_limit:
                retry_after = int(self.window_seconds - (now - self._requests[ip][0])) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Maximum {self.requests_limit} requests per minute.",
                    headers={"Retry-After": str(max(1, retry_after))}
                )

            self._requests[ip].append(now)

    def record_failure(self, request: Request) -> None:
        ip = self._get_client_ip(request)
        now = time.time()

        with self._lock:
            fail_count, lockout_until = self._failures.get(ip, (0, 0.0))
            fail_count += 1
            if fail_count >= self.lockout_threshold:
                lockout_until = now + self.lockout_duration_seconds

            self._failures[ip] = (fail_count, lockout_until)

    def record_success(self, request: Request) -> None:
        ip = self._get_client_ip(request)
        with self._lock:
            if ip in self._failures:
                del self._failures[ip]

    def reset_for_test(self) -> None:
        with self._lock:
            self._requests.clear()
            self._failures.clear()


# Global login rate limiter instance (10 requests/minute, 5 failures triggers 60s lockout)
auth_rate_limiter = InMemoryRateLimiter(
    requests_limit=10,
    window_seconds=60,
    lockout_threshold=5,
    lockout_duration_seconds=60
)
