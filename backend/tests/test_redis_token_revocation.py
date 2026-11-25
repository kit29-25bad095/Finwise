"""
Finora Security Remediation (SEC-01) Test Suite
Redis-Based Distributed JWT Token Revocation & Multi-Worker Verification.

Validates:
1. Successful token revocation and namespaced Redis key creation.
2. Revoked token rejection across API endpoints.
3. Unrevoked token acceptance.
4. Token expiration and automatic TTL behavior.
5. Revocation visibility across independent workers/processes sharing Redis.
6. Redis connection failure and fail-secure behavior.
7. Concurrent revocation requests under multithreaded load.
8. Logout and refresh token rotation regression.
9. Authentication regression (registration and login).
10. Redis outage recovery behavior.
"""

import time
import uuid
import threading
from datetime import timedelta
import pytest
import redis
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    TokenRevocationStore,
    TokenRevocationError,
)


@pytest.fixture(autouse=True)
def clean_redis_revocations():
    """Ensures a clean revocation state before and after every test."""
    TokenRevocationStore.set_redis_client(None)
    TokenRevocationStore.reset()
    yield
    TokenRevocationStore.set_redis_client(None)
    TokenRevocationStore.reset()


def test_01_successful_token_revocation():
    """Requirement 1: Verify token revocation successfully stores jti in Redis with namespaced key."""
    user_id = uuid.uuid4()
    token = create_access_token(subject=user_id, expires_delta=timedelta(minutes=15))

    payload = decode_access_token(token)
    assert payload is not None
    jti = payload["jti"]

    # Revoke token
    success = TokenRevocationStore.revoke_token(token)
    assert success is True

    # Verify key in Redis
    redis_client = TokenRevocationStore.get_redis_client()
    assert redis_client is not None
    key = f"{TokenRevocationStore._get_key_prefix()}{jti}"
    assert redis_client.exists(key) == 1


def test_02_revoked_token_rejection(client: TestClient, seeded_entities):
    """Requirement 2: Verify revoked tokens are rejected by decoder and API endpoints with 401."""
    token = seeded_entities["token_admin_a"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify active
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200

    # Revoke
    TokenRevocationStore.revoke_token(token)

    # Decode must return None
    assert decode_access_token(token) is None

    # API call must return 401 Unauthorized
    resp_revoked = client.get("/api/v1/auth/me", headers=headers)
    assert resp_revoked.status_code == 401
    assert "Invalid or expired" in resp_revoked.json()["detail"]


def test_03_unrevoked_token_acceptance(client: TestClient, seeded_entities):
    """Requirement 3: Verify unrevoked valid tokens are accepted and decoded properly."""
    token = seeded_entities["token_admin_a"]
    headers = {"Authorization": f"Bearer {token}"}

    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == str(seeded_entities["admin_a"].id)

    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@alpha.com"


def test_04_token_expiration_and_ttl_behavior():
    """Requirement 4: Verify Redis TTL matches token expiration, and expired tokens reject independently."""
    user_id = uuid.uuid4()
    # 30-minute token
    token_30m = create_access_token(subject=user_id, expires_delta=timedelta(minutes=30))
    payload_30m = decode_access_token(token_30m)
    assert payload_30m is not None
    jti_30m = payload_30m["jti"]

    TokenRevocationStore.revoke_token(token_30m)

    redis_client = TokenRevocationStore.get_redis_client()
    key_30m = f"{TokenRevocationStore._get_key_prefix()}{jti_30m}"
    ttl_30m = redis_client.ttl(key_30m)
    # TTL should be around 1800 seconds (30 mins)
    assert 1700 <= ttl_30m <= 1800

    # Expired token must be rejected independently by signature/exp verification
    expired_token = create_access_token(subject=user_id, expires_delta=timedelta(seconds=-10))
    # decode_access_token must reject expired token even if not revoked
    assert decode_access_token(expired_token) is None


def test_05_revocation_visibility_across_independent_workers():
    """Requirement 5: Verify revocation in Worker 1 is immediately visible to Worker 2 connected to same Redis."""
    try:
        # Worker 1 connects to Redis
        worker1_redis = redis.Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
        # Worker 2 connects independently to Redis
        worker2_redis = redis.Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)

        token = create_access_token(subject=uuid.uuid4())
        payload = decode_access_token(token)
        assert payload is not None
        jti = payload["jti"]

        # Configure store with Worker 1's client
        TokenRevocationStore.set_redis_client(worker1_redis)
        TokenRevocationStore.revoke_token(token)

        # Worker 2 inspects revocation state
        key = f"{TokenRevocationStore._get_key_prefix()}{jti}"
        assert worker2_redis.exists(key) == 1

        # Switch store to Worker 2 client: Worker 2 must reject token
        TokenRevocationStore.set_redis_client(worker2_redis)
        assert TokenRevocationStore.is_jti_revoked(jti) is True
        assert decode_access_token(token) is None
    finally:
        TokenRevocationStore.set_redis_client(None)


def test_06_redis_connection_failure_fail_secure():
    """Requirement 6: Verify fail-secure behavior when Redis is unavailable (does not silently accept revoked tokens)."""
    try:
        token = create_access_token(subject=uuid.uuid4())
        payload = decode_access_token(token)
        assert payload is not None
        jti = payload["jti"]

        # Point to a dead/unreachable Redis port
        dead_client = redis.Redis.from_url("redis://127.0.0.1:6399/0", socket_timeout=0.2, socket_connect_timeout=0.2)
        TokenRevocationStore.set_redis_client(dead_client)

        # In strict fail-secure mode, token must be treated as revoked / untrusted
        is_revoked = TokenRevocationStore.is_jti_revoked(jti)
        assert is_revoked is True
        assert decode_access_token(token) is None
    finally:
        TokenRevocationStore.set_redis_client(None)


def test_07_concurrent_revocation_requests():
    """Requirement 7: Verify concurrent revocation requests across multiple threads operate safely without race conditions."""
    tokens = [create_access_token(subject=uuid.uuid4()) for _ in range(20)]
    errors = []

    def revoke_worker(tok):
        try:
            success = TokenRevocationStore.revoke_token(tok)
            if not success:
                errors.append("Revoke returned False")
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=revoke_worker, args=(t,)) for t in tokens]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0

    # Verify all 20 tokens are rejected
    for tok in tokens:
        assert decode_access_token(tok) is None


def test_08_logout_and_refresh_token_regression(client: TestClient, seeded_entities):
    """Requirement 8: Verify /auth/logout revokes both access and refresh tokens, and /auth/refresh rotates securely."""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.com", "password": "Password123!"}
    )
    assert login_resp.status_code == 200
    data = login_resp.json()
    access_token = data["access_token"]
    refresh_token = data["refresh_token"]

    # Access API works
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_resp.status_code == 200

    # Call /auth/logout
    logout_resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert logout_resp.status_code == 200

    # Old access token must be revoked
    me_after_logout = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_after_logout.status_code == 401

    # Refreshing using revoked refresh token must fail
    refresh_attempt = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_attempt.status_code == 401


def test_09_authentication_regression(client: TestClient):
    """Requirement 9: Verify complete registration and login regression flows pass with Redis active."""
    reg_payload = {
        "email": "redis_test_user@enterprise.com",
        "password": "StrongPassword123!",
        "full_name": "Redis Security Tester",
        "tenant_name": "Redis Brand Direct",
        "tenant_slug": "redis-brand"
    }
    reg_resp = client.post("/api/v1/auth/register", json=reg_payload)
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert "access_token" in reg_data

    # Login with correct password
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "redis_test_user@enterprise.com", "password": "StrongPassword123!"}
    )
    assert login_resp.status_code == 200
    login_token = login_resp.json()["access_token"]

    # Protected endpoint check
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "redis_test_user@enterprise.com"


def test_10_redis_recovery_behavior():
    """Requirement 10: Verify TokenRevocationStore gracefully recovers when Redis returns online."""
    try:
        token = create_access_token(subject=uuid.uuid4())
        payload = decode_access_token(token)
        assert payload is not None
        jti = payload["jti"]

        # 1. Simulate outage: dead client
        dead_client = redis.Redis.from_url("redis://127.0.0.1:6399/0", socket_timeout=0.2, socket_connect_timeout=0.2)
        TokenRevocationStore.set_redis_client(dead_client)
        assert TokenRevocationStore.is_jti_revoked(jti) is True  # Fails secure during outage

        # 2. Simulate recovery: healthy client
        healthy_client = redis.Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
        TokenRevocationStore.set_redis_client(healthy_client)

        # Before revocation on healthy Redis, unrevoked token is valid again
        assert TokenRevocationStore.is_jti_revoked(jti) is False
        assert decode_access_token(token) is not None

        # Now revoke on healthy Redis
        TokenRevocationStore.revoke_token(token)
        assert TokenRevocationStore.is_jti_revoked(jti) is True
        assert decode_access_token(token) is None
    finally:
        TokenRevocationStore.set_redis_client(None)
