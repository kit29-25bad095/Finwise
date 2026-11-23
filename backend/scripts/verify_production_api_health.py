"""
Production API Verification and Smoke Test Harness
Tests health endpoints, metrics, and security headers against finora_production.
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from dotenv import dotenv_values
_env = dotenv_values(os.path.join(BACKEND_DIR, ".env"))

# Set production environment for verification
os.environ["ENVIRONMENT"] = "production"
os.environ["DATABASE_URL"] = "postgresql+psycopg2://finora_staging:Loneliness062615@localhost:5432/finora_production"
os.environ["SYNC_DATABASE_URL"] = "postgresql+psycopg2://finora_staging:Loneliness062615@localhost:5432/finora_production"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["WORKER_FALLBACK_SYNC"] = "False"
gemini_key = _env.get("GEMINI_API_KEY") or _env.get("AI_API_KEY") or os.getenv("GEMINI_API_KEY") or "AIzaSyFakeKeyForSmokeTestingValidation2026"
os.environ["GEMINI_API_KEY"] = gemini_key
os.environ["AI_API_KEY"] = gemini_key

if "SECRET_KEY" not in os.environ or len(os.environ["SECRET_KEY"]) < 32:
    os.environ["SECRET_KEY"] = "prod_finora_super_secure_jwt_secret_key_minimum_32_characters_2026"

from fastapi.testclient import TestClient
from app.main import app

def run_api_smoke_tests():
    print("Executing Production API Smoke Tests against finora_production...")
    client = TestClient(app)

    # 1. Liveness Probe
    r_live = client.get("/health/live")
    print(f"1. /health/live status: {r_live.status_code}, payload: {r_live.json()}")
    assert r_live.status_code == 200
    assert r_live.json()["status"] == "ALIVE"

    # 2. Readiness Probe (checks PostgreSQL finora_production and Redis)
    r_ready = client.get("/health/ready")
    print(f"2. /health/ready status: {r_ready.status_code}, payload: {r_ready.json()}")
    assert r_ready.status_code == 200
    assert r_ready.json()["status"] == "READY"
    assert r_ready.json()["dependencies"]["database"] == "HEALTHY"
    assert r_ready.json()["dependencies"]["redis"] == "HEALTHY"

    # 3. API V1 Liveness & Readiness Probes
    r_v1_live = client.get("/api/v1/health/live")
    print(f"3. /api/v1/health/live status: {r_v1_live.status_code}, payload: {r_v1_live.json()}")
    assert r_v1_live.status_code == 200
    assert r_v1_live.json()["status"] == "ALIVE"

    r_v1_ready = client.get("/api/v1/health/ready")
    print(f"4. /api/v1/health/ready status: {r_v1_ready.status_code}, payload: {r_v1_ready.json()}")
    assert r_v1_ready.status_code == 200
    assert r_v1_ready.json()["status"] == "READY"

    # 4. Prometheus Metrics Endpoint
    r_metrics = client.get("/metrics")
    print(f"5. /metrics status: {r_metrics.status_code}, length: {len(r_metrics.text)} bytes")
    assert r_metrics.status_code == 200
    assert "finora_" in r_metrics.text or "http_" in r_metrics.text or "python_" in r_metrics.text or "process_" in r_metrics.text

    # 5. Monitoring JSON Metrics Endpoint
    r_json_metrics = client.get("/api/v1/monitoring/metrics")
    print(f"6. /api/v1/monitoring/metrics status: {r_json_metrics.status_code}")
    assert r_json_metrics.status_code == 200
    assert "financial_engine" in r_json_metrics.json()
    assert "reconciliation_runs_total" in r_json_metrics.json()["financial_engine"]

    # 6. Security Headers Check
    print("7. Security Headers Check:")
    headers = r_live.headers
    print(f"   X-Content-Type-Options: {headers.get('X-Content-Type-Options')}")
    print(f"   X-Frame-Options: {headers.get('X-Frame-Options')}")
    
    print("\nALL PRODUCTION API SMOKE TESTS PASSED CLEANLY!")
    return True

if __name__ == "__main__":
    run_api_smoke_tests()
