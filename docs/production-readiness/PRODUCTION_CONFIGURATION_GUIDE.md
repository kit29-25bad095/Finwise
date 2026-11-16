# Finora Production Configuration Guide

**Document ID**: PR-REP-009  
**Version**: 1.0.0  
**Classification**: Enterprise Deployment Specification  
**System**: Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine  
**Target Environment**: AWS / GCP / Azure Staging & Production Clusters  

---

## 1. Executive Overview

This guide details the complete configuration topology, environment variable specifications, connection pool profiles, secret management requirements, and infrastructure tuning parameters required to deploy Finora securely in staging and production environments.

Finora follows the **Twelve-Factor App** configuration methodology. Configuration is strictly separated from code and injected at runtime through environment variables or mounted container secrets.

---

## 2. Environment Variables Reference

### 2.1 Backend Core & Security (`backend/.env`)

| Variable | Type | Default / Example | Required | Production Guidance |
| :--- | :--- | :--- | :--- | :--- |
| `PROJECT_NAME` | string | `Finora` | No | Display name for system logs and API documentation. |
| `ENVIRONMENT` | string | `production` | **Yes** | Valid values: `development`, `staging`, `production`. Disables OpenAPI/Swagger docs in `production`. |
| `LOG_LEVEL` | string | `INFO` | No | Standard Python logging levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `SECRET_KEY` | string | *32+ byte cryptographically random hex* | **Yes** | Used for HMAC-SHA256 signing of session tokens and cryptographic operations. Must be rotated quarterly. |
| `JWT_SECRET_KEY` | string | *32+ byte cryptographically random hex* | **Yes** | Used to sign tenant user access tokens. Must NEVER equal `SECRET_KEY`. |
| `JWT_ALGORITHM` | string | `HS256` | No | Default `HS256`. Enterprise production may configure `RS256` with public/private key pairs. |
| `ACCESS_TOKEN_EXPIRE_MINUTES`| integer| `60` | No | Short-lived JWT lifetime in minutes. Production recommended: 15–60 minutes. |
| `BACKEND_CORS_ORIGINS` | json array | `["https://app.finora.internal"]` | **Yes** | Strict whitelist of origins permitted to call the backend. Never use `*` in production. |

### 2.2 PostgreSQL Database & Connection Pooling

| Variable | Type | Default / Example | Required | Production Guidance |
| :--- | :--- | :--- | :--- | :--- |
| `DATABASE_URL` | string | `postgresql://user:pass@host:5432/finora_prod` | **Yes** | Managed PostgreSQL connection string (AWS RDS / GCP Cloud SQL). |
| `DB_POOL_SIZE` | integer | `20` | No | Base persistent connection pool size per worker process. Recommended: 20–50. |
| `DB_MAX_OVERFLOW` | integer | `10` | No | Maximum burst connections created beyond `DB_POOL_SIZE`. |
| `DB_POOL_TIMEOUT` | integer | `30` | No | Seconds to wait before timing out when no pool connection is available. |
| `DB_POOL_RECYCLE` | integer | `1800` | No | Reconnect after 1800s (30m) to prevent stale socket terminations by firewalls. |
| `DB_SSL_MODE` | string | `require` | **Yes** | Enforces TLS. Production values: `require` or `verify-full` with root CA certificates. |

### 2.3 Redis & Asynchronous Worker Queue

| Variable | Type | Default / Example | Required | Production Guidance |
| :--- | :--- | :--- | :--- | :--- |
| `REDIS_URL` | string | `redis://:auth_token@redis-cluster:6379/0` | **Yes** | Cluster or ElastiCache Redis endpoint with in-transit encryption (TLS `rediss://`). |
| `WORKER_CONCURRENCY` | integer | `4` | No | Number of concurrent background worker threads per node. |
| `WORKER_QUEUE_FALLBACK` | boolean | `false` | No | Set to `false` in production to prevent silent fallback to in-process sync queue. |

### 2.4 AI Investigation Service (Google Gemini)

| Variable | Type | Default / Example | Required | Production Guidance |
| :--- | :--- | :--- | :--- | :--- |
| `AI_PROVIDER` | string | `gemini` | **Yes** | Active LLM adapter: `gemini` or `mock`. Must be `gemini` in production. |
| `GEMINI_API_KEY` | string | *Secret AI Studio / Vertex Key* | **Yes** | Enterprise key for Gemini API calls. Never commit to source control. |
| `GEMINI_MODEL` | string | `gemini-2.0-flash-exp` | No | Configured model. Fallback: `gemini-1.5-pro` or `gemini-1.5-flash`. |
| `GEMINI_TIMEOUT_SECONDS` | integer | `30` | No | Client timeout for LLM inferences. |
| `GEMINI_MAX_RETRIES` | integer | `3` | No | Automatic exponential backoff attempts on 429 rate limit or 503 transient errors. |

### 2.5 Frontend Next.js Client (`frontend/.env.production`)

| Variable | Type | Default / Example | Required | Production Guidance |
| :--- | :--- | :--- | :--- | :--- |
| `NEXT_PUBLIC_API_URL` | string | `https://api.finora.internal/api/v1` | **Yes** | Base URL for REST API calls from client browser. |
| `NEXT_PUBLIC_APP_ENV` | string | `production` | No | Environment identifier displayed in telemetry. |
| `NODE_ENV` | string | `production` | **Yes** | Enables React production optimizations and removes debug bundles. |
| `PORT` | integer | `3100` | No | Listening port for Next.js standalone Node server. |

---

## 3. Production Environment Templates

### 3.1 Backend `.env.production` (Sample)

```ini
# FINORA BACKEND PRODUCTION ENVIRONMENT CONFIGURATION
PROJECT_NAME="Finora Reconciliation Engine"
ENVIRONMENT="production"
LOG_LEVEL="INFO"

# Cryptographic Keys (Must be generated via 'openssl rand -hex 32')
SECRET_KEY="REPLACE_WITH_GENERATED_64_CHAR_HEX_SECRET_KEY"
JWT_SECRET_KEY="REPLACE_WITH_SEPARATE_64_CHAR_HEX_JWT_SECRET_KEY"
JWT_ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=60

# CORS Security Whitelist
BACKEND_CORS_ORIGINS=["https://app.finora.com", "https://reconcile.finora.internal"]

# PostgreSQL Database (Managed RDS / Cloud SQL)
DATABASE_URL="postgresql://finora_app:SECURE_DB_PASSWORD@rds-postgres.internal.finora.com:5432/finora_prod"
DB_POOL_SIZE=25
DB_MAX_OVERFLOW=15
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
DB_SSL_MODE="require"

# Redis Background Processing
REDIS_URL="rediss://:SECURE_REDIS_PASSWORD@redis-cluster.internal.finora.com:6379/0"

# AI Investigation Service
AI_PROVIDER="gemini"
GEMINI_API_KEY="AIzaSy_REPLACE_WITH_VALID_ENTERPRISE_GEMINI_KEY"
GEMINI_MODEL="gemini-2.0-flash-exp"
GEMINI_TIMEOUT_SECONDS=30
GEMINI_MAX_RETRIES=3

# Rate Limiting & Protections
RATE_LIMIT_AUTH="5/minute"
RATE_LIMIT_UPLOAD="30/minute"
RATE_LIMIT_FORENSICS="20/minute"
```

### 3.2 Frontend `.env.production` (Sample)

```ini
# FINORA FRONTEND PRODUCTION ENVIRONMENT CONFIGURATION
NODE_ENV="production"
PORT=3100
NEXT_PUBLIC_API_URL="https://api.finora.com/api/v1"
NEXT_PUBLIC_APP_ENV="production"
```

---

## 4. Key Management & Secret Rotation Strategy

1. **Secret Storage**: All production secrets (`SECRET_KEY`, `JWT_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `GEMINI_API_KEY`) must be stored in a dedicated KMS/Vault service:
   - AWS: AWS Secrets Manager / Parameter Store (SecureString).
   - GCP: Secret Manager.
   - Self-hosted: HashiCorp Vault.
2. **Access Control**: Production secrets must only be decrypted by the container execution task role (ECS Task Role / K8s Service Account) at boot time.
3. **Rotation Cadence**:
   - `JWT_SECRET_KEY`: Rotated quarterly. Dual-verification window supported during rollover.
   - `DATABASE_URL`: Rotated every 180 days with zero-downtime multi-user PostgreSQL user rotation.
   - `GEMINI_API_KEY`: Rotated every 90 days.

---

## 5. Network Architecture & Reverse Proxy Guidelines

```
Client (Browser / API Consumer)
               │ (HTTPS:443)
               ▼
Cloudflare / AWS ALB (TLS Termination, WAF, DDoS Mitigation)
   ├── /api/*   ──────► Nginx Ingress / Reverse Proxy (HTTP:80)
   │                           │ (HTTP:8000)
   │                           ▼
   │                    Gunicorn / Uvicorn ASGI Backend
   │                           │
   │                           ├──► PostgreSQL 16 (TLS:5432)
   │                           ├──► Redis Cluster (TLS:6379)
   │                           └──► Google Gemini API (HTTPS:443 Outbound)
   │
   └── /*       ──────► Next.js Node Server (HTTP:3100)
```

### 5.1 Recommended Nginx Security Ingress Snippet

```nginx
server {
    listen 80;
    server_name api.finora.internal;

    # Enforce request size limit for CSV bulk uploads
    client_max_body_size 50M;

    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Request-ID $request_id;

    # Upstream to Finora FastAPI Backend
    location / {
        proxy_pass http://backend_upstream:8000;
        proxy_read_timeout 60s;
        proxy_connect_timeout 10s;
    }
}
```

---

## 6. Pre-Flight Configuration Verification Checklist

Before opening traffic to a newly deployed environment, DevOps personnel must verify:
- [ ] Database connectivity verified via `GET /health/ready` probe.
- [ ] Redis worker queue health reported as healthy via `/health/ready`.
- [ ] Both `SECRET_KEY` and `JWT_SECRET_KEY` are distinct and $\ge 64$ characters.
- [ ] `BACKEND_CORS_ORIGINS` contains exact production domains, with NO wildcards.
- [ ] `DATABASE_URL` uses `sslmode=require`.
- [ ] `GEMINI_API_KEY` is present and `/health/ready` reports `"ai_provider": "gemini"`.
- [ ] Frontend builds cleanly with `NODE_ENV=production` and points to the secured API gateway.
