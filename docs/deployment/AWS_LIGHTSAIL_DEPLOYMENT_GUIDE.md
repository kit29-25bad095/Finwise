# FINORA — AWS LIGHTSAIL PRODUCTION DEPLOYMENT GUIDE
## Target Region: Mumbai (`ap-south-1`)

- **Author:** Principal Production Release Engineer
- **Date:** November 25, 2026
- **Target Platform:** Amazon Lightsail
- **Target Instance Plan:** 4 GB RAM, 2 vCPUs, 80 GB SSD, 3 TB Transfer ($20/month)
- **Target Operating System:** Ubuntu 22.04 LTS or 24.04 LTS (x86_64)
- **Architecture:** Single-node Docker Compose multi-container production stack
- **Repository Branch:** `deployment/aws-lightsail-preparation`

---

## 1. Architecture & Capacity Planning (4 GB RAM / 2 vCPUs)

Finora’s production container footprint is tuned specifically for the 4 GB RAM / 2 vCPU resource ceiling:

```
+-----------------------------------------------------------------------------------------+
|                  Amazon Lightsail Virtual Private Server (4,096 MB RAM)                 |
|                             Host OS: Ubuntu 22.04 / 24.04 LTS                           |
+-----------------------------------------------------------------------------------------+
| Host OS, systemd, SSH, Docker Engine (~600 MB) + 4 GB Swap File (SSD)                   |
+-----------------------------------------------------------------------------------------+
|                                    Docker Containers                                    |
|                                                                                         |
|  +--------------------+   +---------------------+   +--------------------------------+  |
|  | Nginx Proxy (128M) |-->| Frontend UI (384M)  |   | Outbox Scheduler (192M)        |  |
|  | Port 80 & 443 SSL  |   | Next.js Standalone  |   | Reaper / Dispatcher            |  |
|  +--------------------+   +---------------------+   +--------------------------------+  |
|            |                                                        |                   |
|            v                                                        v                   |
|  +--------------------+                     +----------------------------------------+  |
|  | FastAPI API (896M) |-------------------->| RQ Worker (640M)                       |  |
|  | 2 Uvicorn Workers  |                     | Heavy Reconciliation & Investigations  |  |
|  +--------------------+                     +----------------------------------------+  |
|            |                                                        |                   |
|            +-----------------------+   +----------------------------+                   |
|                                    |   |                                                |
|                                    v   v                                                |
|                    +-------------------------------------+                              |
|                    | Fully Isolated Internal Data Network|                              |
|                    | Zero Public Host Port Bindings      |                              |
|                    +-------------------------------------+                              |
|                                    |   |                                                |
|                  +-----------------+   +------------------+                             |
|                  |                                        |                             |
|                  v                                        v                             |
|  +-------------------------------+      +---------------------------------+             |
|  | PostgreSQL 17 Alpine (768M)   |      | Redis 7 Alpine (256M)           |             |
|  | shared_buffers=128MB          |      | maxmemory=192mb (noeviction)    |             |
|  | Volume: postgres_data         |      | Volume: redis_data              |             |
|  +-------------------------------+      +---------------------------------+             |
|                  |                                        |                             |
|                  +--------------------+-------------------+                             |
|                                       v                                                 |
|               +-----------------------------------------------+                         |
|               | Private Evidence Storage: finora_storage      |                         |
|               | POSIX 0700 / 0600 - /var/finora/storage       |                         |
|               +-----------------------------------------------+                         |
+-----------------------------------------------------------------------------------------+
```

### Memory Budget Allocation
| Service | CPU Limit | Memory Limit | Memory Reservation | Purpose |
| :--- | :---: | :---: | :---: | :--- |
| **`postgres`** | 1.00 vCPU | 768 MB | 256 MB | PostgreSQL 17 relational database |
| **`redis`** | 0.50 vCPU | 256 MB | 64 MB | Redis 7 broker & distributed JWT blacklist |
| **`backend`** | 1.00 vCPU | 896 MB | 384 MB | FastAPI core API (2 Gunicorn workers) |
| **`worker`** | 1.00 vCPU | 640 MB | 256 MB | RQ asynchronous reconciliation worker |
| **`scheduler`** | 0.25 vCPU | 192 MB | 64 MB | Outbox event dispatcher & reaper |
| **`frontend`** | 0.50 vCPU | 384 MB | 128 MB | Next.js 14 standalone SSR frontend |
| **`reverse-proxy`**| 0.25 vCPU | 128 MB | 32 MB | Nginx reverse proxy & TLS termination |
| **Total Docker** | — | **3,264 MB** | **1,184 MB** | **Safe margin for 4,096 MB physical host** |
| **Host OS & Cache**| — | **~832 MB** | — | Ubuntu kernel, Docker daemon, SSH |

---

## 2. Amazon Lightsail Provisioning (Step-by-Step)

### Step 2.1: Create Lightsail Instance
1. Log in to the [AWS Management Console](https://lightsail.aws.amazon.com/) and navigate to **Amazon Lightsail**.
2. Select Region: **Asia Pacific (Mumbai) `ap-south-1`**, Zone `ap-south-1a` or `ap-south-1b`.
3. Select platform: **Linux/Unix**.
4. Select blueprint: **OS Only** -> **Ubuntu 22.04 LTS** (or **Ubuntu 24.04 LTS**).
5. Select instance plan: **$20 USD / month** (4 GB Memory, 2 vCPUs, 80 GB SSD, 3 TB transfer).
6. Name your instance: `finora-production-mumbai`.
7. Click **Create instance**.

### Step 2.2: Attach a Static IP
Lightsail dynamic IPs change on instance stop/restart. A static IP is required:
1. In the Lightsail console, click **Networking**.
2. Click **Create static IP**.
3. Select region `ap-south-1` and attach it to `finora-production-mumbai`.
4. Name the static IP: `finora-prod-static-ip`.
5. Note the allocated public IPv4 address (e.g. `13.233.X.X`).

### Step 2.3: Configure Lightsail Firewall
Under instance **Networking** -> **IPv4 Firewall**, configure strict ingress rules:

| Application | Protocol | Port Range | Source / Restriction | Notes |
| :--- | :---: | :---: | :---: | :--- |
| **SSH** | TCP | `22` | Restrict to Admin IP | Deny 0.0.0.0/0 to prevent brute-force attacks |
| **HTTP** | TCP | `80` | `0.0.0.0/0` (Custom/Any) | Required for ACME HTTP-01 challenge & redirect |
| **HTTPS**| TCP | `443` | `0.0.0.0/0` (Custom/Any) | Encrypted production web traffic |
| *All Others* | — | — | **BLOCKED** | Ports 5432 (Postgres) and 6379 (Redis) MUST NOT be added! |

---

## 3. Host System Initialization

SSH into your new Lightsail instance:
```bash
ssh -i ~/.ssh/LightsailDefaultKey-ap-south-1.pem ubuntu@<STATIC_IP>
```

### Step 3.1: Configure Swap Space (Mandatory for 4 GB RAM)
Because heavy operations (Docker image builds, large reconciliations) can briefly burst memory usage, configure a 4 GB swap file on the 80 GB SSD:
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Persist across reboots
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Tune swappiness for database performance
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
```

### Step 3.2: Install Docker Engine and Docker Compose v2
```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release awscli jq tar gzip

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Enable Docker without sudo for ubuntu user
sudo usermod -aG docker ubuntu
newgrp docker
```

---

## 4. Application Deployment Execution

### Step 4.1: Clone Repository and Checkout Dedicated Branch
```bash
git clone https://github.com/kit29-25bad095/Finwise.git finora
cd finora
git checkout deployment/aws-lightsail-preparation
```

### Step 4.2: Provision Production Secrets (`.env.production`)
Copy the audited configuration template:
```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

Generate high-entropy secrets and populate `.env.production`:
```bash
# 1. Generate SECRET_KEY
openssl rand -hex 32

# 2. Generate POSTGRES_PASSWORD
openssl rand -hex 24

# 3. Generate REDIS_PASSWORD
openssl rand -hex 24
```

Edit `.env.production` using `nano .env.production`:
- Insert the generated `SECRET_KEY`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD`.
- Insert your live `GEMINI_API_KEY`.
- Set `BACKEND_CORS_ORIGINS=["https://yourdomain.com"]` (match your production domain).
- Configure S3 backup settings:
  ```env
  AWS_DEFAULT_REGION=ap-south-1
  AWS_S3_BACKUP_BUCKET=finora-production-backups-mumbai
  AWS_S3_BACKUP_PREFIX=daily-snapshots
  AWS_ACCESS_KEY_ID=AKIA...
  AWS_SECRET_ACCESS_KEY=...
  ```

### Step 4.3: Bootstrap TLS / SSL Certificates
Run the bootstrap certificate script so Nginx can start immediately without crashing:
```bash
chmod +x scripts/bootstrap_ssl.sh
./scripts/bootstrap_ssl.sh yourdomain.com
```

### Step 4.4: Build and Launch Multi-Container Infrastructure
```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Verify all 7 containers are healthy:
```bash
docker compose -f docker-compose.prod.yml ps
```
Expected output:
```
NAME               IMAGE                   STATUS                   PORTS
finora-proxy       nginx:1.27-alpine       Up (healthy)             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
finora-frontend    finora-frontend         Up (healthy)             3100/tcp
finora-backend     finora-backend          Up (healthy)             8000/tcp
finora-worker      finora-worker           Up                       
finora-scheduler   finora-scheduler        Up                       
finora-postgres    postgres:17-alpine      Up (healthy)             5432/tcp
finora-redis       redis:7-alpine          Up (healthy)             6379/tcp
```

### Step 4.5: Obtain Real Let's Encrypt TLS Certificate
Once your domain DNS A-record points to the Lightsail static IP:
```bash
sudo apt-get install -y certbot

# Request certificate via webroot challenge
sudo certbot certonly --webroot -w ./nginx/conf.d \
  -d yourdomain.com -d www.yourdomain.com \
  --email admin@yourdomain.com --agree-tos --no-eff-email

# Deploy certificate to Nginx directory
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ./nginx/certs/finora.crt
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ./nginx/certs/finora.key
sudo chmod 600 ./nginx/certs/finora.key

# Reload Nginx without downtime
docker compose -f docker-compose.prod.yml exec reverse-proxy nginx -s reload
```

---

## 5. Post-Deployment Verification & Smoke Tests

Run smoke tests directly against the running stack:

1. **Verify Backend Liveness Probe:**
   ```bash
   curl -I http://localhost/health/live
   # HTTP/1.1 301 Moved Permanently (redirects to https)
   curl -k -I https://localhost/health/live
   # HTTP/2 200 (OK)
   ```

2. **Verify Frontend Availability:**
   ```bash
   curl -k -I https://localhost/
   # HTTP/2 200 (OK)
   ```

3. **Verify Database Connectivity and Migration Status:**
   ```bash
   docker compose -f docker-compose.prod.yml exec backend alembic current
   ```

4. **Verify Redis Distributed JWT Revocation & Security Status:**
   ```bash
   docker compose -f docker-compose.prod.yml exec redis redis-cli -a "$REDIS_PASSWORD" ping
   # PONG
   ```

---

## 6. Zero-Downtime Application Update Procedure

When updating code on the server:
```bash
cd ~/finora
git fetch origin
git checkout deployment/aws-lightsail-preparation
git pull origin deployment/aws-lightsail-preparation

# Build updated images
docker compose -f docker-compose.prod.yml --env-file .env.production build backend worker frontend

# Apply new database migrations
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm backend alembic upgrade head

# Rolling restart of backend and frontend
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --no-deps backend frontend worker scheduler
```

---

## 7. Emergency Rollback Procedure

If a critical incident occurs after deployment:
1. **Rollback Git Commit:**
   ```bash
   git checkout <PREVIOUS_STABLE_COMMIT>
   ```
2. **Re-run Migrations (if backward migration script exists):**
   ```bash
   docker compose -f docker-compose.prod.yml exec backend alembic downgrade -1
   ```
3. **Rebuild and Restart Containers:**
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   ```
4. **Restore Database from S3 if Data Was Corrupted:**
   ```bash
   chmod +x scripts/restore_from_s3.sh
   ./scripts/restore_from_s3.sh <TIMESTAMP_OF_LAST_HEALTHY_BACKUP>
   ```
