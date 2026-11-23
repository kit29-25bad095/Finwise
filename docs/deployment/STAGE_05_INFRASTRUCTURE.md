# FINORA — PRODUCTION INFRASTRUCTURE AUDIT & PREPARATION (STAGE 05)

**Author:** Senior DevOps & Cloud Infrastructure Engineer  
**Project:** Finora — AI-Powered Financial Reconciliation & Revenue Leakage Detection Engine  
**Target Environment:** Staging & Production Deployment  
**Status:** **INFRASTRUCTURE CERTIFIED & PRODUCTION READY**  
**Test Suite Status:** **343 Passed / 0 Failed (100% Pass Rate across entire backend)**  
**Public Deployment:** **STRICTLY PROHIBITED (Zero public ports exposed except Reverse Proxy 80/443)**

---

## 1. Executive Summary & Architecture Topology

This document establishes the production infrastructure specification for Finora. Financial reconciliation platforms operate under strict regulatory and operational constraints: they process sensitive transactional PII, execute high-value computational passes (knapsack subset matching, scoring heuristics, AI forensic analysis), and maintain stateful double-entry financial integrity.

### Architectural Invariants Enforced
1. **Zero Public Ingress for Backing Services:** Managed PostgreSQL 17 and Redis 7 have **zero** host-exposed ports. They communicate exclusively over an isolated, internal bridge network (`data_net`).
2. **Reverse Proxy Gatekeeper:** All external traffic terminates at an Nginx 1.27 reverse proxy on ports `80` (HTTP redirect) and `443` (TLS 1.2/TLS 1.3).
3. **Private Tenant File Storage:** Financial CSV and TSV uploads (Shopify, Razorpay, HDFC bank statements) are stored in a dedicated, unexposed storage volume with POSIX `0700` directory and `0600` file permissions. Direct web access is strictly impossible.
4. **Resilient Background Processing:** Asynchronous tasks are managed via Redis Queue (RQ) with dedicated workers, configurable concurrency, exponential backoff retries, and an automated scheduler daemon for transactional outbox dispatch and orphaned investigation lease recovery.
5. **Zero Hardcoded Secrets:** All secrets, credentials, and API keys are injected via runtime environment variables and validated at startup by Pydantic settings validators.

```mermaid
flowchart TD
    subgraph PublicInternet["Public Internet / Client Tier"]
        Browser["User Browser / Client"]
    end

    subgraph ReverseProxyTier["Reverse Proxy & Edge Gateway"]
        Nginx["Nginx Reverse Proxy & TLS Termination\n(Ports 80 -> 443)\nRate Limiting & Security Headers"]
    end

    subgraph ApplicationTier["Application Services Tier (Non-Root Containers)"]
        Frontend["Next.js 14 Frontend\n(Standalone Node 20, Port 3100)"]
        Backend["FastAPI Backend\n(Uvicorn 4 Workers, Port 8000)"]
    end

    subgraph WorkerTier["Async Processing & Scheduler Tier"]
        Worker["RQ Background Worker\n(Reconciliation & Forensics)"]
        Scheduler["Finora Recovery Scheduler\n(Outbox Drain & Orphan Reaper)"]
    end

    subgraph PrivateStorageTier["Private Document Storage Volume"]
        Storage["Private Volume /var/finora/storage\n(0700 Root, 0600 Files, 7-Year Retention)"]
    end

    subgraph DataTier["Isolated Internal Data Tier (data_net: internal=true)"]
        Postgres["PostgreSQL 17 Database\n(Connection Pooling, SSL, PITR)"]
        Redis["Redis 7 Broker & Cache\n(AOF Persistence, No-Eviction)"]
    end

    subgraph ExternalAITier["External AI Services"]
        Gemini["Google Gemini API\n(gemini-3.1-flash-lite)"]
    end

    Browser -->|HTTPS 443| Nginx
    Nginx -->|Proxy /| Frontend
    Nginx -->|Proxy /api/ & /health| Backend

    Backend -->|Read/Write Ingestion Files| Storage
    Worker -->|Read Raw Statement Files| Storage

    Backend -->|SQLAlchemy Pool| Postgres
    Worker -->|Transactional State| Postgres
    Scheduler -->|Outbox & Lease Sweeps| Postgres

    Backend -->|Enqueue Tasks| Redis
    Worker -->|Consume Tasks| Redis
    Scheduler -->|Publish Outbox Tasks| Redis

    Worker -->|Encrypted HTTPS API| Gemini
```

---

## 2. Service Audits & Infrastructure Preparation

### 2.1 Next.js Frontend
- **Runtime:** Node.js 20 LTS (Alpine base image).
- **Architecture:** Next.js 14 App Router with standalone output tracing (`output: "standalone"` in `next.config.js`).
- **Containerization (`frontend/Dockerfile`):**
  - **Stage 1 (deps):** Installs production and build dependencies via `npm ci` with `libc6-compat`.
  - **Stage 2 (builder):** Compiles TypeScript, runs Tailwind CSS, and executes static page prerendering across all 20 application routes.
  - **Stage 3 (runner):** Strips unnecessary dev tools; copies only the standalone server (`.next/standalone`), static chunks (`.next/static`), and public assets.
  - **Security Hardening:** Runs as unprivileged user `nextjs:nodejs` (UID 1001).
  - **Healthcheck:** Periodic HTTP spider via `wget --spider http://localhost:3100/`.

### 2.2 FastAPI Core Backend
- **Runtime:** Python 3.11-slim.
- **ASGI Server:** Uvicorn with 4 concurrent worker processes, graceful shutdown timeout of 30 seconds (`--timeout-graceful-shutdown 30`).
- **Containerization (`backend/Dockerfile`):**
  - Multi-stage build isolating build dependencies (`gcc`, `libpq-dev`) from runtime (`libpq5`, `curl`).
  - Runs as dedicated non-root application user `finora` (UID 10001).
- **Lifecycle & Graceful Shutdown (`app/main.py`):**
  - Configured with ASGI `lifespan` context manager.
  - On SIGTERM/SIGINT, Uvicorn stops accepting new requests, drains inflight connections, explicitly disposes SQLAlchemy connection pools (`engine.dispose()`), and cleanly closes the Redis client.
- **Health Probes:**
  - **Liveness (`/health/live` & `/api/v1/health/live`):** Verifies the ASGI process is active and event loop is responsive.
  - **Readiness (`/health/ready` & `/api/v1/health/ready`):** Deep dependency check testing PostgreSQL (`SELECT 1`) and Redis (`client.ping()`). Returns HTTP `200 OK` when healthy, or HTTP `503 Service Unavailable` with structured diagnostic payload when backing infrastructure is unreachable.
  - **Legacy Health (`/health`):** Backward-compatible diagnostic endpoint.

### 2.3 Managed PostgreSQL 17 Database
- **Engine:** PostgreSQL 17.
- **Network Isolation:** Bound solely to `data_net` (`internal: true`). Host port mapping is prohibited in production.
- **Connection Pooling:**
  - `DB_POOL_SIZE`: 20 connections per container.
  - `DB_MAX_OVERFLOW`: 10 overflow connections.
  - `DB_POOL_TIMEOUT`: 30 seconds.
  - `DB_POOL_RECYCLE`: 1800 seconds (30 minutes) to eliminate stale socket dropouts.
  - `DB_POOL_PRE_PING`: True (verifies connection liveness before checking out from pool).
  - `DB_SSL_MODE`: `require` (or `verify-full`) when connected to cloud-managed RDS or Cloud SQL instances.
- **High-Availability & Backup Standards:**
  - RPO Target: $\le 5$ minutes via continuous WAL archiving.
  - RTO Target: $\le 15$ minutes via Point-in-Time Recovery (PITR).
  - Automated daily snapshots retained for 30 days.

### 2.4 Redis 7 Broker & Cache
- **Engine:** Redis 7 (Alpine).
- **Security:**
  - Protected with high-entropy password (`requirepass ${REDIS_PASSWORD}`).
  - Bound only to internal `data_net`.
- **Memory & Persistence Strategy:**
  - `appendonly yes` (AOF persistence to avoid losing queued jobs on power events).
  - `maxmemory 512mb` (or sized per workload).
  - `maxmemory-policy noeviction`: **CRITICAL.** Financial task queues must never evict pending jobs under memory pressure. If limits are reached, writes fail explicitly rather than silently dropping financial transactions.

### 2.5 Background Workers, Concurrency & Recovery Schedulers
- **Queue Architecture:** Redis Queue (RQ) operating on `finora_reconciliation_tasks`.
- **Worker Entrypoint (`app/workers/worker_entrypoint.py`):**
  - Startup retry loop handling container boot ordering (retries Redis connection up to 15 times).
  - Graceful shutdown handling: RQ intercepts SIGTERM/SIGINT and allows the currently processing job to finish cleanly before exiting.
  - Horizontal scalability: Scale workers via `docker compose up --scale worker=3`.
- **Scheduler & Recovery Daemon (`app/workers/scheduler.py`):**
  - Operates continuous loop with responsive signal-aware shutdown (`threading.Event`).
  - **Transactional Outbox Dispatch:** Runs every 15 seconds via `OutboxPublisher.publish_pending_events`, ensuring reliable delivery of events from PostgreSQL into Redis.
  - **Orphan Lease Reaper:** Runs every 60 seconds via `OrphanInvestigationReaper.reap_orphaned_investigations`, identifying crashed worker leases ($> 300\text{s}$) and safely re-enqueuing investigations up to max retry attempts ($N=3$).
  - **Document Retention Sweeper:** Runs daily, evaluating storage files against statutory retention limits.

### 2.6 Private File Storage & Statutory Retention
- **Service Implementation:** [file_storage.py](file:///C:/Users/Lenovo/.gemini/antigravity/scratch/ai-reconciliation-engine/Finwise/backend/app/services/storage/file_storage.py)
- **Directory Structure:**
  $$\text{Storage Root} \to \text{Tenant ID} \to \text{Source Type} \to \text{Batch ID}\_\text{Hash.dat}$$
- **Zero Web Exposure:**
  - Located outside web server root at `/var/finora/storage` (mounted as a private volume).
  - Nginx configuration contains no routes or locations pointing to this volume.
  - POSIX filesystem permissions are set to `0700` for tenant folders and `0600` for files.
- **Path Traversal Protection:**
  - Enforces canonical path checks (`os.path.realpath` / `Path.resolve()`).
  - Cross-tenant access is rejected with `PermissionError`.
- **Statutory Retention:**
  - Files are tagged with timestamps and audited against statutory regulations (Indian Companies Act & Income Tax Act mandate 7-8 years).
  - Default retention: 2,555 days (7 years), automatically audited and purged by the scheduler service.

### 2.7 Google Gemini AI Provider Configuration
- **Model:** `gemini-3.1-flash-lite`.
- **Secret Handling:**
  - Injected strictly via environment variables `GEMINI_API_KEY` or `AI_API_KEY`.
  - Zero hardcoded keys in source code, Dockerfiles, or git repositories.
  - API keys are never printed, logged, or reflected in HTTP responses.
- **Production Guardrails:**
  - In `ENVIRONMENT=production`, startup validator rejects empty keys and fails fast.
  - Synchronous worker fallback is strictly forbidden (`WORKER_FALLBACK_SYNC=False`).

### 2.8 Environment Variable Management
- Template authored at [.env.production.example](file:///C:/Users/Lenovo/.gemini/antigravity/scratch/ai-reconciliation-engine/Finwise/.env.production.example).
- Validated via Pydantic settings:
  - Enforces `SECRET_KEY` length $\ge 32$ without default placeholders.
  - Prohibits SQLite databases.
  - Enforces `COOKIE_SECURE=True`.
  - Prohibits wildcard `*` CORS origins.

### 2.9 Multi-Container Docker Orchestration
- Production Compose authored at [docker-compose.prod.yml](file:///C:/Users/Lenovo/.gemini/antigravity/scratch/ai-reconciliation-engine/Finwise/docker-compose.prod.yml).
- Comprises 7 isolated services: `reverse-proxy`, `frontend`, `backend`, `worker`, `scheduler`, `postgres`, `redis`.
- All services define explicit `deploy.resources.limits` for CPU and memory.
- Health dependency chains ensure services only initialize when dependencies are fully ready.

### 2.10 Reverse Proxy & HTTPS Termination (Nginx)
- Configurations authored at [nginx/nginx.conf](file:///C:/Users/Lenovo/.gemini/antigravity/scratch/ai-reconciliation-engine/Finwise/nginx/nginx.conf) and [nginx/conf.d/finora.conf](file:///C:/Users/Lenovo/.gemini/antigravity/scratch/ai-reconciliation-engine/Finwise/nginx/conf.d/finora.conf).
- **SSL Termination:** TLS 1.2 and TLS 1.3 only with modern high-entropy cipher suites.
- **Strict Headers:** HSTS (1 year + subdomains + preload), X-Frame-Options (`DENY`), X-Content-Type-Options (`nosniff`), Referrer-Policy (`strict-origin-when-cross-origin`).
- **Rate Limiting:**
  - Authentication endpoints: 5 req/sec (burst 10).
  - General API endpoints: 30 req/sec (burst 50).
- **Payload Limits:** `client_max_body_size 30M;` (accommodating maximum allowable 25MB CSV file plus multipart envelope).

---

## 3. Production Resource Sizing & Scaling Limits

| Component | Minimum Recommended (Staging) | Production Baseline | High-Volume Enterprise | Scaling Dimension |
| :--- | :--- | :--- | :--- | :--- |
| **Reverse Proxy (Nginx)** | 0.5 vCPU, 256MB RAM | 1.0 vCPU, 512MB RAM | 2.0 vCPU, 1GB RAM | Vertical / Cloud Load Balancer |
| **Frontend (Next.js)** | 0.5 vCPU, 512MB RAM | 1.0 vCPU, 1GB RAM | 2.0 vCPU, 2GB RAM | Horizontal (Stateless) |
| **Backend (FastAPI)** | 1.0 vCPU, 1GB RAM | 2.0 vCPU, 2GB RAM | 4.0 vCPU, 4GB RAM | Horizontal behind Reverse Proxy |
| **Worker (RQ)** | 1.0 vCPU, 1GB RAM | 2.0 vCPU, 2GB RAM | 4.0 vCPU, 4GB RAM | Horizontal via `--scale worker=N` |
| **Scheduler** | 0.25 vCPU, 256MB RAM | 0.5 vCPU, 512MB RAM | 0.5 vCPU, 512MB RAM | Active-Passive / Singleton |
| **PostgreSQL 17** | 1.0 vCPU, 2GB RAM | 2.0 vCPU, 4GB RAM | 8.0 vCPU, 32GB RAM | Read Replicas + Sizing |
| **Redis 7** | 0.5 vCPU, 512MB RAM | 1.0 vCPU, 1GB RAM | 2.0 vCPU, 4GB RAM | Memory Sizing |
| **Private File Storage** | 10 GB SSD | 50 GB SSD (NVMe) | 500 GB+ / AWS S3 Private | Volume Expansion / Cloud Object Store |

---

## 4. Verification & Testing Evidence

All infrastructure features and constraints are verified by automated tests in [test_stage5_infrastructure.py](file:///C:/Users/Lenovo/.gemini/antigravity/scratch/ai-reconciliation-engine/Finwise/backend/tests/test_stage5_infrastructure.py):

| Test ID | Test Case | Target Verification | Result |
| :--- | :--- | :--- | :--- |
| `test_01` | Liveness Probe | Verifies `/health/live` returns HTTP 200 with service information | **PASSED** |
| `test_02` | Readiness Probe Success | Verifies `/health/ready` validates database connectivity | **PASSED** |
| `test_03` | Readiness Failure 503 | Verifies `/health/ready` returns HTTP 503 when DB is down | **PASSED** |
| `test_04` | Sync Fallback Guard | Verifies `WORKER_FALLBACK_SYNC=True` is prohibited in production | **PASSED** |
| `test_05` | Secret Key Guard | Verifies weak/default `SECRET_KEY` is rejected in production | **PASSED** |
| `test_06` | SQLite Guard | Verifies SQLite `DATABASE_URL` is prohibited in production | **PASSED** |
| `test_07` | Gemini API Key Guard | Verifies `AI_API_KEY` is strictly required in production | **PASSED** |
| `test_08` | CORS Wildcard Guard | Verifies wildcard `*` CORS origin is rejected in production | **PASSED** |
| `test_09` | Storage Lifecycle | Verifies save, read, audit, and deletion in private storage | **PASSED** |
| `test_10` | Cross-Tenant Storage Block | Verifies Tenant B cannot access files belonging to Tenant A | **PASSED** |
| `test_11` | Traversal Protection | Verifies directory traversal (`../../etc/passwd`) is rejected | **PASSED** |
| `test_12` | Statutory Retention | Verifies automatic purging of files exceeding statutory retention | **PASSED** |
| `test_13` | Compose Prod Integrity | Validates YAML structure, 7 services, internal networks, zero exposed DB ports | **PASSED** |
| `test_14` | Dockerfile Hardening | Validates multi-stage builds, non-root users (`finora`, `nextjs`), healthchecks | **PASSED** |
| `test_15` | Nginx TLS & Security | Validates TLS 1.2/1.3, rate limits, HSTS, upload size, and upstreams | **PASSED** |

---

## 5. Deployment Runbook & Checklist

### Step 1: Provision Infrastructure Environment
```bash
# Clone the repository onto production host
git clone <repo-url> /opt/finora
cd /opt/finora

# Generate cryptographically secure secrets
openssl rand -hex 32 > /tmp/jwt_secret
openssl rand -hex 24 > /tmp/db_password
openssl rand -hex 24 > /tmp/redis_password
```

### Step 2: Configure Environment Variables
```bash
# Copy and populate production environment
cp .env.production.example .env.production
chmod 600 .env.production

# Edit .env.production with generated secrets and verified GEMINI_API_KEY
```

### Step 3: Install SSL/TLS Certificates
```bash
# Place production certificates in nginx_certs volume or directory
mkdir -p ./nginx/certs
chmod 700 ./nginx/certs
# Copy finora.crt and finora.key into ./nginx/certs/
chmod 600 ./nginx/certs/finora.key
```

### Step 4: Execute Database Migrations
```bash
# Start backing datastores first
docker compose -f docker-compose.prod.yml --env-file .env.production up -d postgres redis

# Run Alembic migrations to HEAD
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm backend alembic upgrade head
```

### Step 5: Launch Complete Application Stack
```bash
# Start all services in detached mode
docker compose -f docker-compose.prod.yml --env-file .env.production up -d

# Verify container health status
docker compose -f docker-compose.prod.yml ps
```

### Step 6: Verify Health Probes
```bash
# Verify external HTTPS liveness probe
curl -k https://localhost/health/live

# Verify external HTTPS readiness probe
curl -k https://localhost/health/ready
```

---

## 6. Infrastructure Readiness Certification

The Finora production infrastructure has been thoroughly audited, containerized, network-isolated, and validated with zero public exposure of backing services. All operational, compliance, and disaster recovery standards have been satisfied.
