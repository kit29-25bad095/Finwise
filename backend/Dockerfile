# Multi-stage production Dockerfile for Finora FastAPI Backend & Workers
# Stage 1: Build virtual environment with compiled wheels
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# Stage 2: Hardened runtime image
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    FINORA_STORAGE_DIR="/var/finora/storage"

# Install only minimal runtime dependencies (libpq5 for PostgreSQL, curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Create unprivileged application user and private storage directory
RUN addgroup --system --gid 10001 finora && \
    adduser --system --uid 10001 --gid 10001 --home /app --no-create-home finora && \
    mkdir -p /var/finora/storage && \
    chown -R finora:finora /app /var/finora/storage && \
    chmod 700 /var/finora/storage

# Copy application source code
COPY --chown=finora:finora . .

USER finora

EXPOSE 8000

# Container liveness health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health/live || exit 1

# Default: start API server. Can be overridden in docker-compose for workers/scheduler
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--timeout-graceful-shutdown", "30"]
