import io
import uuid
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.core.middleware import SecurityHeadersMiddleware
from app.core.rate_limit import RateLimitMiddleware, limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    TokenRevocationStore,
    verify_password,
    get_password_hash,
)
from app.services.ingestion.sanitizer import sanitize_csv_cell


def test_01_security_headers_present(client: TestClient):
    """Domain 13: Verify OWASP recommended security headers are injected into HTTP responses."""
    resp = client.get("/health")
    assert resp.status_code == 200
    headers = resp.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "geolocation=()" in headers.get("Permissions-Policy", "")
    assert "default-src 'self'" in headers.get("Content-Security-Policy", "")


def test_02_rate_limiting_auth_brute_force(client: TestClient):
    """Domain 4: Verify sliding-window rate limiter blocks brute-force login attempts with 429."""
    RateLimitMiddleware.FORCE_ENABLED = True
    limiter.reset()
    try:
        # Auth endpoint limit is 10 requests / minute
        for i in range(10):
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": f"brute_force_{i}@example.com", "password": "wrong_password"}
            )
            # Expect 401 Unauthorized for incorrect credentials
            assert resp.status_code == 401
            assert "X-RateLimit-Limit" in resp.headers
            assert resp.headers["X-RateLimit-Limit"] == "10"

        # 11th request must be rejected with 429 Too Many Requests
        rate_limited_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "brute_force_11@example.com", "password": "wrong_password"}
        )
        assert rate_limited_resp.status_code == 429
        assert "Retry-After" in rate_limited_resp.headers
        assert rate_limited_resp.headers.get("X-RateLimit-Remaining") == "0"
        data = rate_limited_resp.json()
        assert "Rate limit exceeded" in data["detail"]
    finally:
        RateLimitMiddleware.FORCE_ENABLED = False
        limiter.reset()


def test_03_jwt_revocation_on_logout(client: TestClient, seeded_entities):
    """Domain 5: Verify JWT token is immediately revoked upon calling /auth/logout."""
    token = seeded_entities["token_admin_a"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify token is active
    resp_me = client.get("/api/v1/auth/me", headers=headers)
    assert resp_me.status_code == 200
    assert resp_me.json()["email"] == "admin@alpha.com"

    # Call logout to revoke token
    resp_logout = client.post("/api/v1/auth/logout", headers=headers)
    assert resp_logout.status_code == 200
    assert "logged out" in resp_logout.json()["message"].lower()

    # Subsequent request using the revoked token must fail with 401
    resp_after = client.get("/api/v1/auth/me", headers=headers)
    assert resp_after.status_code == 401
    assert "Invalid or expired" in resp_after.json()["detail"]


def test_04_jwt_refresh_token_rotation_and_revocation(client: TestClient, seeded_entities):
    """Domain 5: Verify refresh token rotation: old refresh token is revoked upon consumption."""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.com", "password": "Password123!"}
    )
    assert login_resp.status_code == 200
    data = login_resp.json()
    first_access = data["access_token"]
    first_refresh = data["refresh_token"]
    assert first_refresh is not None

    # Consume refresh token to obtain a new pair
    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh}
    )
    assert refresh_resp.status_code == 200
    refreshed_data = refresh_resp.json()
    second_access = refreshed_data["access_token"]
    second_refresh = refreshed_data["refresh_token"]

    assert second_access != first_access
    assert second_refresh != first_refresh

    # Attempting to replay the consumed refresh token must fail with 401
    replay_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh}
    )
    assert replay_resp.status_code == 401
    assert "Invalid, expired, or revoked" in replay_resp.json()["detail"]

    # The new access token must work
    resp_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second_access}"})
    assert resp_me.status_code == 200


def test_05_refresh_token_cannot_access_protected_apis(client: TestClient, seeded_entities):
    """Domain 5: Verify refresh tokens (type='refresh') cannot be used as Bearer access tokens."""
    refresh_token = create_refresh_token(subject=str(seeded_entities["admin_a"].id))
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert resp.status_code == 401
    assert "Invalid or expired" in resp.json()["detail"]


def test_06_expired_jwt_rejected(client: TestClient, seeded_entities):
    """Domain 5: Verify expired JWT access tokens are strictly rejected."""
    expired_token = create_access_token(
        subject=str(seeded_entities["admin_a"].id),
        expires_delta=timedelta(seconds=-10)
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert "Invalid or expired" in resp.json()["detail"]


def test_07_tampered_jwt_signature_rejected(client: TestClient, seeded_entities):
    """Domain 5: Verify tokens signed with invalid secret or tampered payloads are rejected."""
    valid_token = seeded_entities["token_admin_a"]
    # Tamper with signature by modifying the last few characters
    tampered_token = valid_token[:-4] + "wxyz"
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert resp.status_code == 401
    assert "Invalid or expired" in resp.json()["detail"]


def test_08_secure_cookie_authentication(client: TestClient, seeded_entities):
    """Domain 2: Verify HTTP-only, SameSite cookies are set on login and work for authentication."""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.com", "password": "Password123!"}
    )
    assert login_resp.status_code == 200
    cookies = login_resp.cookies
    assert "access_token" in cookies
    assert "refresh_token" in cookies

    # Access /auth/me using only the access_token cookie (no Authorization header)
    resp_me = client.get("/api/v1/auth/me", cookies={"access_token": cookies["access_token"]})
    assert resp_me.status_code == 200
    assert resp_me.json()["email"] == "admin@alpha.com"


def test_09_upload_file_extension_validation(client: TestClient, seeded_entities):
    """Domain 11: Verify non-whitelisted file extensions (.exe, .sh) are rejected with 400."""
    headers = seeded_entities["headers_a_admin"]
    malicious_files = [
        ("exploit.exe", b"MZ\x90\x00\x03\x00\x00\x00"),
        ("script.sh", b"#!/bin/bash\nrm -rf /"),
        ("document.pdf", b"%PDF-1.4 ..."),
    ]
    for filename, content in malicious_files:
        resp = client.post(
            "/api/v1/ingestion/upload",
            headers=headers,
            data={"source_type": "SHOPIFY"},
            files={"file": (filename, io.BytesIO(content), "application/octet-stream")}
        )
        assert resp.status_code == 400
        assert "Invalid file extension" in resp.json()["detail"]


def test_10_upload_file_size_limit(client: TestClient, seeded_entities, monkeypatch):
    """Domain 11: Verify file upload exceeding MAX_UPLOAD_SIZE_BYTES returns 413 Payload Too Large."""
    headers = seeded_entities["headers_a_admin"]
    # Temporarily set MAX_UPLOAD_SIZE_BYTES to 1024 bytes (1 KB) for the test
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 1024)

    oversized_data = b"order_id,amount,status\n" + (b"ORD100,500.00,PAID\n" * 100)
    assert len(oversized_data) > 1024

    resp = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "SHOPIFY"},
        files={"file": ("large_statement.csv", io.BytesIO(oversized_data), "text/csv")}
    )
    assert resp.status_code == 413
    assert "exceeds maximum allowed size" in resp.json()["detail"].lower()


def test_11_csv_formula_injection_defense():
    """Domain 9: Verify CSV formula injection triggers (=, +, -, @, |, %, tab, return) are escaped."""
    attack_vectors = [
        ("=1+1", "'=1+1"),
        ("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"),
        ("+2+2", "'+2+2"),
        ("-SUM(1,2)", "'-SUM(1,2)"),
        ("@SUM(A1:A10)", "'@SUM(A1:A10)"),
        ("|calc.exe", "'|calc.exe"),
        ("%0Acalc.exe", "'%0Acalc.exe"),
        ("\tcmd|", "'\tcmd|"),
        ("\rcmd|", "'\rcmd|"),
        ("  =FORMULA", "'  =FORMULA"),
    ]
    for raw_input, expected_sanitized in attack_vectors:
        sanitized = sanitize_csv_cell(raw_input)
        assert sanitized == expected_sanitized, f"Failed for {raw_input}: got {sanitized}"

    # Verify benign business text is unaltered
    benign_cells = [
        "INV-2026-00123",
        "Payment received via UPI",
        "ORD_HDFC_9921",
        "12500.00",
        "",
        None,
    ]
    for benign in benign_cells:
        sanitized = sanitize_csv_cell(benign)
        expected = "" if benign is None else str(benign)
        assert sanitized == expected


def test_12_rbac_auditor_cannot_mutate(client: TestClient, seeded_entities):
    """Domain 6: Verify RBAC: AUDITOR role is strictly prohibited from mutating data."""
    auditor_headers = seeded_entities["headers_a_auditor"]

    # 1. Auditor cannot upload ingestion files
    csv_content = b"order_id,amount\nORD1,100.00\n"
    resp_upload = client.post(
        "/api/v1/ingestion/upload",
        headers=auditor_headers,
        data={"source_type": "SHOPIFY"},
        files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")}
    )
    assert resp_upload.status_code == 403
    assert "Operation requires one of the following roles" in resp_upload.json()["detail"]

    # 2. Auditor cannot trigger reconciliation runs
    resp_recon = client.post(
        "/api/v1/reconciliation/runs",
        headers=auditor_headers,
        json={"parameters": {}}
    )
    assert resp_recon.status_code == 403
    assert "Operation requires one of the following roles" in resp_recon.json()["detail"]


def test_13_cross_tenant_isolation_idor(client: TestClient, seeded_entities):
    """Domain 7 & 8: Verify Tenant A user cannot access Tenant B resources (IDOR prevention)."""
    headers_a = seeded_entities["headers_a_admin"]
    tenant_b_id = str(seeded_entities["tenant_b"].id)

    # Tenant A attempts to explicitly query Tenant B using X-Tenant-ID header
    tampered_headers = {**headers_a, "X-Tenant-ID": tenant_b_id}
    resp = client.get("/api/v1/ingestion/batches", headers=tampered_headers)
    assert resp.status_code == 403
    assert "not have authorized access" in resp.json()["detail"].lower()


def test_14_sql_injection_resilience(client: TestClient, seeded_entities):
    """Domain 12: Verify SQL injection payloads in parameters do not produce syntax errors or data leaks."""
    headers = seeded_entities["headers_a_admin"]
    sqli_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "1 UNION SELECT null, null, null--",
        "' OR 1=1--",
    ]
    for payload in sqli_payloads:
        resp = client.get(
            f"/api/v1/ingestion/batches?source_type={payload}",
            headers=headers
        )
        # Parameterized queries evaluate cleanly: returns 200 with empty list or handled error
        assert resp.status_code in (200, 400, 404, 422)
        assert "syntax error" not in resp.text.lower()
        assert "operationalerror" not in resp.text.lower()


def test_15_production_settings_validation():
    """Domain 1 & 3: Verify strict configuration validation rejects insecure production settings."""
    # 1. Reject weak secret key in production
    with pytest.raises(ValueError, match="SECRET_KEY of at least 32 characters"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="short-key",
            DATABASE_URL="postgresql://user:pass@localhost:5432/finora_prod",
            SYNC_DATABASE_URL="postgresql://user:pass@localhost:5432/finora_prod",
            AI_API_KEY="valid-gemini-key",
            WORKER_FALLBACK_SYNC=False,
            BACKEND_CORS_ORIGINS=["https://app.finora.in"]
        )

    # 2. Reject SQLite in production
    with pytest.raises(ValueError, match="PostgreSQL is required in production"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a-very-long-production-grade-secret-key-32-chars",
            DATABASE_URL="sqlite:///./prod.db",
            SYNC_DATABASE_URL="sqlite:///./prod.db",
            AI_API_KEY="valid-gemini-key",
            WORKER_FALLBACK_SYNC=False,
            BACKEND_CORS_ORIGINS=["https://app.finora.in"]
        )

    # 3. Reject wildcard CORS origin in production
    with pytest.raises(ValueError, match="Wildcard '\\*' CORS origin is strictly prohibited"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a-very-long-production-grade-secret-key-32-chars",
            DATABASE_URL="postgresql://user:pass@localhost:5432/finora_prod",
            SYNC_DATABASE_URL="postgresql://user:pass@localhost:5432/finora_prod",
            AI_API_KEY="valid-gemini-key",
            WORKER_FALLBACK_SYNC=False,
            BACKEND_CORS_ORIGINS=["*"]
        )


def test_16_sensitive_data_redaction(seeded_entities):
    """Domain 14: Verify user passwords are encrypted using bcrypt and hashes are non-reversible."""
    admin = seeded_entities["admin_a"]
    assert admin.hashed_password != "Password123!"
    assert admin.hashed_password.startswith("$2b$") or admin.hashed_password.startswith("$2a$")
    assert verify_password("Password123!", admin.hashed_password) is True
    assert verify_password("WrongPassword!", admin.hashed_password) is False
