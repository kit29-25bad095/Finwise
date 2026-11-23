from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects OWASP & NIST recommended baseline HTTP security headers on all responses:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY (Clickjacking protection)
    - X-XSS-Protection: 1; mode=block
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: Restricts access to sensitive browser features
    - Content-Security-Policy: Strict script/frame execution policy
    - Strict-Transport-Security: Enforced in production to mandate TLS/HTTPS
    """
    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; object-src 'none';"

        # Enforce HSTS when running in production or over HTTPS
        is_https = request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"
        if is_https or settings.ENVIRONMENT.lower() == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        return response
