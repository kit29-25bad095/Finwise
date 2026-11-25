"""
Finora Production Infrastructure Static Validation Test Suite
==============================================================
Validates:
1. Docker Compose production manifest (docker-compose.prod.yml) structure, syntax, and schema.
2. Strict network segregation (data_net is internal, postgres & redis are unexposed).
3. Memory budgeting tailored for 4 GB RAM / 2 vCPU Amazon Lightsail server.
4. Log rotation constraints on all container definitions.
5. Healthcheck and restart policy coverage across all services.
6. Nginx configuration (nginx.conf and conf.d/finora.conf) security headers, rate limiting, and upstreams.
7. Environment variable parity between docker-compose.prod.yml and .env.production.example.
"""

import os
import re
from pathlib import Path
import pytest
import yaml


@pytest.fixture
def repo_root():
    """Finds repository root relative to tests directory."""
    return Path(__file__).resolve().parent.parent.parent


def test_01_docker_compose_schema_and_syntax(repo_root):
    """Verify docker-compose.prod.yml parses cleanly and contains required top-level sections."""
    compose_path = repo_root / "docker-compose.prod.yml"
    assert compose_path.exists(), "docker-compose.prod.yml not found"

    with open(compose_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    assert "version" in cfg
    assert "services" in cfg
    assert "networks" in cfg
    assert "volumes" in cfg

    required_services = {"reverse-proxy", "frontend", "backend", "worker", "scheduler", "postgres", "redis"}
    assert required_services.issubset(set(cfg["services"].keys()))


def test_02_network_isolation_and_no_public_backing_services(repo_root):
    """Verify backing services (postgres, redis, worker, scheduler, backend) have zero public host ports."""
    compose_path = repo_root / "docker-compose.prod.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # 1. data_net must be internal: true
    assert cfg["networks"]["data_net"]["internal"] is True

    # 2. Only reverse-proxy is permitted to have 'ports' exposed to host
    for s_name, s_data in cfg["services"].items():
        if "ports" in s_data:
            assert s_name == "reverse-proxy", f"Security violation! Service '{s_name}' exposes host ports directly: {s_data['ports']}"
            # Verify only ports 80 and 443
            ports = s_data["ports"]
            assert any("80:80" in str(p) for p in ports)
            assert any("443:443" in str(p) for p in ports)
            assert len(ports) == 2

    # 3. postgres and redis must be connected ONLY to data_net
    assert cfg["services"]["postgres"]["networks"] == ["data_net"]
    assert cfg["services"]["redis"]["networks"] == ["data_net"]


def test_03_memory_budget_for_4gb_lightsail(repo_root):
    """Verify container memory limits sum to <= 3,500 MB to prevent host OOM on 4 GB RAM VPS."""
    compose_path = repo_root / "docker-compose.prod.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    total_limit_mb = 0
    total_reservation_mb = 0

    for s_name, s_data in cfg["services"].items():
        resources = s_data.get("deploy", {}).get("resources", {})
        limits = resources.get("limits", {})
        reservations = resources.get("reservations", {})

        assert "memory" in limits, f"Service {s_name} missing memory limit"
        mem_str = limits["memory"]
        assert mem_str.endswith("M"), f"Expected memory in MB (e.g. 512M), got {mem_str}"
        limit_mb = int(mem_str[:-1])
        total_limit_mb += limit_mb

        if "memory" in reservations:
            res_str = reservations["memory"]
            total_reservation_mb += int(res_str[:-1])

    # Sizing invariants
    assert total_limit_mb <= 3500, f"Total memory limits ({total_limit_mb} MB) exceed 3,500 MB budget for 4 GB RAM server!"
    assert total_limit_mb == 3264, f"Expected exactly 3,264 MB budgeted limits, got {total_limit_mb} MB"
    assert total_reservation_mb <= 1500


def test_04_log_rotation_on_all_services(repo_root):
    """Verify json-file log rotation is configured across every container to protect SSD."""
    compose_path = repo_root / "docker-compose.prod.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    for s_name, s_data in cfg["services"].items():
        logging_cfg = s_data.get("logging", {})
        assert logging_cfg.get("driver") == "json-file", f"Service {s_name} missing json-file logging"
        opts = logging_cfg.get("options", {})
        assert opts.get("max-size") == "20m", f"Service {s_name} has invalid max-size: {opts.get('max-size')}"
        assert opts.get("max-file") == "5", f"Service {s_name} has invalid max-file: {opts.get('max-file')}"


def test_05_healthchecks_and_restart_policies(repo_root):
    """Verify container restart policy and healthchecks for dependent services."""
    compose_path = repo_root / "docker-compose.prod.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    for s_name, s_data in cfg["services"].items():
        assert s_data.get("restart") in ("always", "unless-stopped"), f"Service {s_name} missing resilient restart policy"

    # Services requiring healthchecks
    healthchecked_services = ["frontend", "backend", "postgres", "redis"]
    for s_name in healthchecked_services:
        s_data = cfg["services"][s_name]
        assert "healthcheck" in s_data, f"Service {s_name} missing healthcheck"
        assert "test" in s_data["healthcheck"], f"Service {s_name} missing healthcheck test command"


def test_06_nginx_configuration_security_and_routing(repo_root):
    """Verify Nginx configuration files contain security headers, SSL directives, and rate limits."""
    nginx_conf = repo_root / "nginx" / "nginx.conf"
    finora_conf = repo_root / "nginx" / "conf.d" / "finora.conf"

    assert nginx_conf.exists()
    assert finora_conf.exists()

    finora_text = finora_conf.read_text(encoding="utf-8")

    # Security headers
    assert "Strict-Transport-Security" in finora_text
    assert "X-Frame-Options" in finora_text
    assert "X-Content-Type-Options" in finora_text
    assert "Referrer-Policy" in finora_text
    assert "Permissions-Policy" in finora_text

    # Modern TLS
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in finora_text
    assert "ssl_certificate /etc/nginx/certs/finora.crt;" in finora_text
    assert "ssl_certificate_key /etc/nginx/certs/finora.key;" in finora_text

    # Upstreams and ACME challenge
    assert "upstream backend_upstream" in finora_text
    assert "upstream frontend_upstream" in finora_text
    assert "location /.well-known/acme-challenge/" in finora_text
    assert "limit_req_zone" in finora_text


def test_07_env_production_documentation_parity(repo_root):
    """Verify .env.production.example documents all critical environment variables."""
    env_example = repo_root / "env.production.example"
    if not env_example.exists():
        env_example = repo_root / ".env.production.example"
    assert env_example.exists()

    env_text = env_example.read_text(encoding="utf-8")

    critical_vars = [
        "SECRET_KEY",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_URL",
        "REDIS_PASSWORD",
        "REDIS_URL",
        "STORAGE_DIR",
        "FINORA_STORAGE_DIR",
        "FILE_RETENTION_DAYS",
        "JWT_REVOCATION_PREFIX",
        "JWT_REVOCATION_FAIL_SECURE",
        "WEB_CONCURRENCY",
        "BACKEND_CORS_ORIGINS",
        "AWS_DEFAULT_REGION",
        "AWS_S3_BACKUP_BUCKET",
    ]

    for var in critical_vars:
        assert var in env_text, f"Critical variable {var} missing from .env.production.example"


def test_08_certbot_ssl_and_backup_scripts(repo_root):
    """Verify TLS bootstrap, renewal, and S3 backup scripts have correct paths and safeguards."""
    compose_path = repo_root / "docker-compose.prod.yml"
    with open(compose_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    proxy_volumes = cfg["services"]["reverse-proxy"]["volumes"]
    assert any("./nginx/certs:/etc/nginx/certs:ro" in v for v in proxy_volumes), "Nginx certs host bind mount missing"
    assert any("./certbot/www:/var/www/certbot:ro" in v for v in proxy_volumes), "Certbot challenge host bind mount missing"

    # Verify scripts
    bootstrap_script = repo_root / "scripts" / "bootstrap_ssl.sh"
    renew_script = repo_root / "scripts" / "renew_certs.sh"
    backup_script = repo_root / "scripts" / "backup_to_s3.sh"
    restore_script = repo_root / "scripts" / "restore_from_s3.sh"

    assert bootstrap_script.exists()
    assert renew_script.exists()
    assert backup_script.exists()
    assert restore_script.exists()

    bootstrap_text = bootstrap_script.read_text(encoding="utf-8")
    assert "./nginx/certs" in bootstrap_text
    assert "./certbot/www" in bootstrap_text

    renew_text = renew_script.read_text(encoding="utf-8")
    assert "certbot renew" in renew_text
    assert "nginx -s reload" in renew_text
    assert "chmod 600" in renew_text

    backup_text = backup_script.read_text(encoding="utf-8")
    assert "finora_production-backups-mumbai" in backup_text or "AWS_S3_BACKUP_BUCKET" in backup_text
    assert "AES256" in backup_text

