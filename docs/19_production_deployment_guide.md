# Finora Phase 7 — Production Deployment & Infrastructure Guide

**Document ID:** `FINORA-DOC-019`  
**Classification:** DevOps & Systems Architecture  
**Status:** READY FOR STAGING / PILOT  
**Author:** DevOps Engineer & Senior Systems Architect  
**Deployment Scope:** Next.js 14 Standalone Frontend, FastAPI Core Backend, PostgreSQL 16, Redis 7 Worker Cluster

---

## 1. Architecture Overview & Topology

Finora is deployed as a secure, containerized Modular Monolith with separate worker processes for asynchronous background tasks.

```
                    Internet / Corporate VPN
                               │
                               ▼
                    [AWS ALB / Cloudflare WAF]
                    (SSL Termination • DDoS Defense)
                     │                      │
                     ▼ (Port 3100)          ▼ (Port 8000)
             [Next.js 14 Frontend]   [FastAPI Core Engine]
             (Vercel / Container)    (Gunicorn + Uvicorn)
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     │                                             │
                     ▼                                             ▼
          [PostgreSQL 16 Managed]                       [Redis 7 Cluster]
          (NUMERIC 18,4 • Multi-AZ)                     (RQ Background Workers)
```

---

## 2. Environment Variables Reference

> [!CAUTION]
> Never commit actual passwords, private keys, or API tokens into version control. The values below are structural references.

### 2.1 Backend Core Configuration (`.env`)

```ini
# System Environment
ENVIRONMENT=production
PROJECT_NAME="Finora — Financial Reconciliation & Revenue Leakage Engine"
API_V1_STR=/api/v1

# Security & Tokens (Generate with: openssl rand -hex 32)
SECRET_KEY=9f8e7d6c5b4a3928170f1e2d3c4b5a69788796a5b4c3d2e1f0a9b8c7d6e5f4a3
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Database Configuration (Managed PostgreSQL)
DATABASE_URL=postgresql://finora_user:StrongSecurePassword123!@postgres.internal:5432/finora_prod
SYNC_DATABASE_URL=postgresql://finora_user:StrongSecurePassword123!@postgres.internal:5432/finora_prod

# Redis & RQ Worker Cluster
REDIS_URL=redis://:RedisAuthToken456!@redis.internal:6379/0
WORKER_FALLBACK_SYNC=false

# Google Gemini AI Forensic Gateway (Optional / Configurable)
AI_PROVIDER=gemini
AI_MODEL=gemini-2.0-flash
AI_API_KEY=AIzaSy...your_gemini_api_key_here
AI_TEMPERATURE=0.1
AI_MAX_TOKENS=2048

# Financial Calculation Defaults
DEFAULT_CURRENCY=INR
DEFAULT_FEE_OVERCHARGE_TOLERANCE=0.05
DEFAULT_SETTLEMENT_CUTOFF_TIME=23:00
DEFAULT_MAX_KNAPSACK_BOUND=5

# Cross-Origin Resource Sharing (CORS)
BACKEND_CORS_ORIGINS=["https://finora.yourdomain.com", "http://localhost:3100"]
```

### 2.2 Frontend Configuration (`.env.production`)

```ini
NODE_ENV=production
NEXT_PUBLIC_API_URL=https://api.finora.yourdomain.com/api/v1
```

---

## 3. Step-by-Step Deployment Runbook

### Step 1: Pre-Deployment Infrastructure Provisioning
1. Provision managed **PostgreSQL 16** (AWS RDS or Google Cloud SQL) with `UTF-8` encoding.
2. Provision managed **Redis 7** (ElastiCache or Cloud Memorystore) with persistence enabled.
3. Configure VPC security groups ensuring database and Redis ports (`5432`, `6379`) are reachable **only** from the backend and worker subnets.

### Step 2: Database Migration Execution
Before launching the application server, apply all versioned migrations:
```bash
cd backend
alembic upgrade head
```
Verify that the `alembic_version` table is updated to the latest revision (`007_phase5_forensic_investigations`).

### Step 3: Backend Deployment with Gunicorn & Uvicorn
Launch the backend container using `gunicorn_conf.py`:
```bash
cd backend
gunicorn -c gunicorn_conf.py app.main:app
```

### Step 4: Background Worker Cluster Initialization
Start one or more dedicated RQ worker containers:
```bash
cd backend
python -m rq worker -u "${REDIS_URL}" high default low
```

### Step 5: Frontend Next.js Deployment
Deploy the standalone Next.js build:
```bash
cd frontend
npm ci
npm run build
node server.js
```

---

## 4. Multi-Container Deployment via Docker Compose

For pilot testing or isolated staging environments:
```bash
# 1. Populate environment variables
cp .env.example .env.production

# 2. Build and launch all services with health checks
docker-compose -f docker-compose.prod.yml up --build -d

# 3. Verify health status
docker-compose -f docker-compose.prod.yml ps
```

---

## 5. Health Probes & Load Balancer Target Groups

Configure your cloud load balancer with these standard probe targets:
- **Liveness Probe:** `GET /health/live` (Interval: 10s, Timeout: 3s, Success threshold: 1, Failure threshold: 3).
- **Readiness Probe:** `GET /health/ready` (Verifies database connectivity; returns 200 OK or 503 Service Unavailable).
- **Executive System Health:** `GET /health` (Returns detailed component status for internal NOC monitoring).
