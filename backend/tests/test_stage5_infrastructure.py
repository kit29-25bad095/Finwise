import os
import uuid
import time
import yaml
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.core.config import Settings, settings
from app.services.storage.file_storage import PrivateFileStorageService
from app.workers.worker_entrypoint import run_worker
from app.workers.scheduler import run_scheduler_loop, shutdown_event

client = TestClient(app)


# ==============================================================================
# 1. Health Checks (Liveness and Readiness Probes)
# ==============================================================================

def test_01_liveness_probe_returns_200_alive():
    """Verify liveness probe returns HTTP 200 with service information."""
    resp = client.get("/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ALIVE"
    assert data["service"] == "Finora Financial Engine"

    # Also test API v1 prefixed route
    resp_v1 = client.get("/api/v1/health/live")
    assert resp_v1.status_code == 200
    assert resp_v1.json()["status"] == "ALIVE"


def test_02_readiness_probe_success():
    """Verify readiness probe checks dependencies and returns HTTP 200."""
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "READY"
    assert "database" in data["dependencies"]
    assert data["dependencies"]["database"] == "HEALTHY"


def test_03_readiness_probe_fails_503_when_database_down():
    """Verify readiness probe returns HTTP 503 SERVICE UNAVAILABLE when database is down."""
    with patch("app.main.get_db_session") as mock_db:
        mock_session = MagicMock()
        mock_session.execute.side_effect = OperationalError("connection refused", {}, None)
        mock_db.return_value = [mock_session]

        # Use app.dependency_overrides to simulate database failure
        from app.core.database import get_db_session
        def failing_db():
            session = MagicMock()
            session.execute.side_effect = OperationalError("connection refused", {}, None)
            yield session

        app.dependency_overrides[get_db_session] = failing_db
        try:
            resp = client.get("/health/ready")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "NOT_READY"
            assert "UNHEALTHY" in data["dependencies"]["database"]
        finally:
            app.dependency_overrides.pop(get_db_session, None)


# ==============================================================================
# 2. Production Settings & Security Guardrails Validation
# ==============================================================================

def test_04_production_settings_rejects_worker_fallback_sync():
    """Verify production settings validator rejects synchronous worker fallback."""
    with pytest.raises(ValueError, match="WORKER_FALLBACK_SYNC must be False in production"):
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=True,
            SECRET_KEY="c" * 32,
            DATABASE_URL="postgresql://user:pass@host:5432/db",
            SYNC_DATABASE_URL="postgresql://user:pass@host:5432/db",
            AI_PROVIDER="gemini",
            AI_API_KEY="valid-key",
            BACKEND_CORS_ORIGINS=["https://app.finora.in"],
        )


def test_05_production_settings_rejects_weak_secret_key():
    """Verify production settings validator rejects default or short SECRET_KEY."""
    with pytest.raises(ValueError, match="non-default SECRET_KEY"):
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=False,
            SECRET_KEY="finora-super-secure-production-ready-jwt-secret-key-32-chars-min",
            DATABASE_URL="postgresql://user:pass@host:5432/db",
            SYNC_DATABASE_URL="postgresql://user:pass@host:5432/db",
            AI_PROVIDER="gemini",
            AI_API_KEY="valid-key",
            BACKEND_CORS_ORIGINS=["https://app.finora.in"],
        )


def test_06_production_settings_rejects_sqlite_database():
    """Verify production settings validator prohibits SQLite in production."""
    with pytest.raises(ValueError, match="PostgreSQL is required in production"):
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=False,
            SECRET_KEY="c" * 32,
            DATABASE_URL="sqlite:///./test.db",
            SYNC_DATABASE_URL="sqlite:///./test.db",
            AI_PROVIDER="gemini",
            AI_API_KEY="valid-key",
            BACKEND_CORS_ORIGINS=["https://app.finora.in"],
        )


def test_07_production_settings_rejects_missing_gemini_api_key():
    """Verify production settings validator requires AI_API_KEY when provider is gemini."""
    with pytest.raises(ValueError, match="AI_API_KEY is required in production"):
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=False,
            SECRET_KEY="c" * 32,
            DATABASE_URL="postgresql://user:pass@host:5432/db",
            SYNC_DATABASE_URL="postgresql://user:pass@host:5432/db",
            AI_PROVIDER="gemini",
            AI_API_KEY="",
            BACKEND_CORS_ORIGINS=["https://app.finora.in"],
        )


def test_08_production_settings_rejects_wildcard_cors():
    """Verify production settings validator strictly rejects wildcard '*' CORS origins."""
    with pytest.raises(ValueError, match="Wildcard '\\*' CORS origin is strictly prohibited"):
        Settings(
            ENVIRONMENT="production",
            WORKER_FALLBACK_SYNC=False,
            SECRET_KEY="c" * 32,
            DATABASE_URL="postgresql://user:pass@host:5432/db",
            SYNC_DATABASE_URL="postgresql://user:pass@host:5432/db",
            AI_PROVIDER="gemini",
            AI_API_KEY="valid-key",
            BACKEND_CORS_ORIGINS=["*"],
        )


# ==============================================================================
# 3. Private File Storage & Statutory Retention
# ==============================================================================

def test_09_private_file_storage_lifecycle(tmp_path):
    """Verify save, read, and delete operations within tenant storage."""
    with patch.object(settings, "STORAGE_DIR", str(tmp_path)):
        tenant_id = uuid.uuid4()
        batch_id = uuid.uuid4()
        content = b"Shopify,Order,Amount\n#1001,4999.00\n"
        sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        # 1. Save
        rel_path = PrivateFileStorageService.save_batch_file(
            tenant_id=tenant_id,
            batch_id=batch_id,
            source_type="SHOPIFY",
            file_bytes=content,
            file_hash_sha256=sha
        )
        assert rel_path.startswith(str(tenant_id))

        # 2. Read
        read_content = PrivateFileStorageService.read_batch_file(tenant_id, rel_path)
        assert read_content == content

        # 3. Audit
        audit = PrivateFileStorageService.audit_storage_security()
        assert audit["public_web_accessible"] is False
        assert audit["exists"] is True

        # 4. Delete
        deleted = PrivateFileStorageService.delete_batch_file(tenant_id, rel_path)
        assert deleted is True

        # Verify not found after delete
        with pytest.raises(FileNotFoundError):
            PrivateFileStorageService.read_batch_file(tenant_id, rel_path)


def test_10_private_file_storage_blocks_cross_tenant_access(tmp_path):
    """Verify that tenant A cannot read files belonging to tenant B."""
    with patch.object(settings, "STORAGE_DIR", str(tmp_path)):
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        batch_id = uuid.uuid4()
        content = b"Confidential financial statement"

        rel_path = PrivateFileStorageService.save_batch_file(
            tenant_id=tenant_a,
            batch_id=batch_id,
            source_type="HDFC",
            file_bytes=content,
            file_hash_sha256="abc1234567890def"
        )

        # Tenant B attempts to read Tenant A's file
        with pytest.raises(PermissionError, match="Access denied: file does not belong to tenant"):
            PrivateFileStorageService.read_batch_file(tenant_b, rel_path)


def test_11_private_file_storage_blocks_directory_traversal(tmp_path):
    """Verify that path traversal attempts are detected and rejected."""
    with patch.object(settings, "STORAGE_DIR", str(tmp_path)):
        tenant_id = uuid.uuid4()
        with pytest.raises(PermissionError, match="Access denied: path is outside private storage root"):
            PrivateFileStorageService.read_batch_file(tenant_id, "../../etc/passwd")


def test_12_statutory_retention_purge(tmp_path):
    """Verify retention cleanup deletes files older than retention policy."""
    with patch.object(settings, "STORAGE_DIR", str(tmp_path)):
        tenant_id = uuid.uuid4()
        batch_id = uuid.uuid4()
        rel_path = PrivateFileStorageService.save_batch_file(
            tenant_id=tenant_id,
            batch_id=batch_id,
            source_type="RAZORPAY",
            file_bytes=b"old statement",
            file_hash_sha256="1234567890abcdef"
        )

        file_full_path = tmp_path / rel_path
        # Set file modification time to 10 years ago (3650 days)
        ten_years_ago = time.time() - (3650 * 86400)
        os.utime(file_full_path, (ten_years_ago, ten_years_ago))

        # Purge files older than 2555 days (7 years)
        purged = PrivateFileStorageService.purge_expired_files(retention_days=2555)
        assert purged == 1
        assert not file_full_path.exists()


# ==============================================================================
# 4. Production Docker and Reverse Proxy Infrastructure Verification
# ==============================================================================

def test_13_docker_compose_prod_configuration_integrity():
    """Verify docker-compose.prod.yml parses cleanly and enforces security isolation."""
    compose_path = Path(__file__).resolve().parent.parent.parent / "docker-compose.prod.yml"
    assert compose_path.exists(), "docker-compose.prod.yml must exist"

    with open(compose_path, "r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)

    services = compose.get("services", {})
    required_services = {"reverse-proxy", "frontend", "backend", "worker", "scheduler", "postgres", "redis"}
    assert required_services.issubset(set(services.keys())), f"Missing services in docker-compose.prod.yml: {required_services - set(services.keys())}"

    # Verify internal data network isolation
    networks = compose.get("networks", {})
    assert "data_net" in networks
    assert networks["data_net"].get("internal") is True, "data_net must be internal=true"

    # Verify internal backing datastores (postgres and redis) do NOT expose host ports
    assert "ports" not in services["postgres"], "PostgreSQL must NOT expose ports to host in production"
    assert "ports" not in services["redis"], "Redis must NOT expose ports to host in production"

    # Verify only reverse proxy exposes ports 80 and 443
    proxy_ports = services["reverse-proxy"].get("ports", [])
    assert "80:80" in proxy_ports and "443:443" in proxy_ports

    # Verify resource limits on all services
    for s_name, s_def in services.items():
        limits = s_def.get("deploy", {}).get("resources", {}).get("limits", {})
        assert "cpus" in limits and "memory" in limits, f"Service {s_name} is missing resource cpu/memory limits"


def test_14_production_dockerfiles_integrity():
    """Verify Dockerfiles use multi-stage builds, non-root users, and healthchecks."""
    repo_root = Path(__file__).resolve().parent.parent.parent

    # 1. Backend Dockerfile
    backend_df = repo_root / "backend" / "Dockerfile"
    assert backend_df.exists()
    b_content = backend_df.read_text(encoding="utf-8")
    assert "AS builder" in b_content, "Backend Dockerfile must be multi-stage"
    assert "USER finora" in b_content, "Backend must run as unprivileged user finora"
    assert "HEALTHCHECK" in b_content, "Backend must specify a HEALTHCHECK instruction"

    # 2. Frontend Dockerfile
    frontend_df = repo_root / "frontend" / "Dockerfile"
    assert frontend_df.exists()
    f_content = frontend_df.read_text(encoding="utf-8")
    assert "AS runner" in f_content, "Frontend Dockerfile must be multi-stage"
    assert "USER nextjs" in f_content, "Frontend must run as unprivileged user nextjs"
    assert "HEALTHCHECK" in f_content, "Frontend must specify a HEALTHCHECK instruction"


def test_15_nginx_reverse_proxy_configuration_integrity():
    """Verify Nginx configuration includes TLS 1.2/1.3, rate limiting, and security headers."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    nginx_conf = repo_root / "nginx" / "conf.d" / "finora.conf"
    assert nginx_conf.exists()

    content = nginx_conf.read_text(encoding="utf-8")
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in content
    assert "Strict-Transport-Security" in content
    assert "X-Frame-Options" in content
    assert "limit_req_zone" in content
    assert "proxy_pass http://backend_upstream;" in content
    assert "proxy_pass http://frontend_upstream;" in content
    assert "client_max_body_size 30M;" in content
