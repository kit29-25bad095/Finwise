import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, status, Depends, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db_session
from app.core.middleware import SecurityHeadersMiddleware
from app.core.rate_limit import RateLimitMiddleware
from app.core.monitoring.logging import configure_structured_logging
from app.core.monitoring.middleware import ObservabilityMiddleware
from app.api.v1 import auth, tenants, ingestion, reconciliation, leakage, forensic, monitoring, dashboard
from app.workers.queue import check_worker_queue_health

logger = logging.getLogger("finora.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: configure structured logging
    configure_structured_logging(environment=settings.ENVIRONMENT)
    logger.info("Finora Financial Engine starting up in %s environment...", settings.ENVIRONMENT)
    yield
    # Graceful Shutdown: close database pools and redis client cleanly
    logger.info("Finora Financial Engine shutting down...")
    try:
        from app.core.database import engine
        engine.dispose()
        logger.info("Database connection pool cleanly disposed.")
    except Exception as e:
        logger.warning("Error disposing database engine pool during shutdown: %s", e)
    try:
        from app.workers.queue import _redis_client
        if _redis_client is not None:
            _redis_client.close()
            logger.info("Redis client connection cleanly closed.")
    except Exception as e:
        logger.warning("Error closing Redis client during shutdown: %s", e)


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Deterministic Financial Reconciliation & Revenue Leakage Detection Engine for Indian D2C Enterprises.",
    version="1.0.0",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# 1. Observability Middleware (Correlation ID, Latency, Metrics, Unhandled Exception Protection)
app.add_middleware(ObservabilityMiddleware)

# 2. Rate Limiting Middleware (Tiered sliding-window brute-force and abuse protection)
app.add_middleware(RateLimitMiddleware)

# 3. Security Headers Middleware (CSP, HSTS, X-Content-Type-Options, Frame-Options, etc.)
app.add_middleware(SecurityHeadersMiddleware)

# 4. CORS Middleware (Production allowlist with restricted methods and explicit headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Origin",
        "X-Requested-With",
        "X-Tenant-ID",
        "X-Correlation-ID",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "Retry-After",
    ],
)

# Register API Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(tenants.router, prefix=settings.API_V1_STR)
app.include_router(ingestion.router, prefix=settings.API_V1_STR)
app.include_router(reconciliation.router, prefix=settings.API_V1_STR)
app.include_router(leakage.router, prefix=settings.API_V1_STR)
app.include_router(forensic.router, prefix=settings.API_V1_STR)
app.include_router(dashboard.router, prefix=settings.API_V1_STR)
app.include_router(monitoring.router)


@app.get("/health", status_code=status.HTTP_200_OK, tags=["System"])
@app.get(f"{settings.API_V1_STR}/health", status_code=status.HTTP_200_OK, tags=["System"])
def healthcheck(db: Session = Depends(get_db_session)):
    db_status = "HEALTHY"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"UNHEALTHY: {str(e)}"

    return {
        "status": "ONLINE",
        "service": "Finora Financial Engine",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
        "database": db_status
    }


@app.get("/health/live", status_code=status.HTTP_200_OK, tags=["System"])
@app.get(f"{settings.API_V1_STR}/health/live", status_code=status.HTTP_200_OK, tags=["System"])
def liveness():
    """Liveness probe: verifies process is alive and event loop responds."""
    return {
        "status": "ALIVE",
        "service": "Finora Financial Engine",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health/ready", tags=["System"])
@app.get(f"{settings.API_V1_STR}/health/ready", tags=["System"])
def readiness(db: Session = Depends(get_db_session)):
    """
    Readiness probe: verifies essential backing services (PostgreSQL, Redis, and AI Provider).
    Returns HTTP 200 if all backing dependencies are healthy.
    Returns HTTP 503 if any required service is unreachable or degraded.
    """
    dependencies = {}
    is_healthy = True

    # 1. Database connectivity check
    try:
        db.execute(text("SELECT 1"))
        dependencies["database"] = "HEALTHY"
    except Exception as e:
        dependencies["database"] = f"UNHEALTHY: {str(e)}"
        is_healthy = False

    # 2. Redis queue connectivity check
    try:
        from app.workers.queue import get_redis_client
        client = get_redis_client()
        if client:
            client.ping()
            dependencies["redis"] = "HEALTHY"
        elif settings.ENVIRONMENT == "test":
            dependencies["redis"] = "SKIPPED_TEST"
        elif not settings.WORKER_FALLBACK_SYNC or settings.ENVIRONMENT == "production":
            dependencies["redis"] = "UNAVAILABLE"
            is_healthy = False
        else:
            dependencies["redis"] = "FALLBACK_SYNC_LOCAL"
    except Exception as e:
        if settings.ENVIRONMENT == "production" or not settings.WORKER_FALLBACK_SYNC:
            dependencies["redis"] = f"UNHEALTHY: {str(e)}"
            is_healthy = False
        else:
            dependencies["redis"] = f"DEGRADED_FALLBACK: {str(e)}"

    queue_health = check_worker_queue_health()
    dependencies["worker_queue"] = queue_health

    ai_configured = bool(settings.resolved_ai_api_key)
    dependencies["ai_provider"] = {
        "provider": settings.AI_PROVIDER,
        "model": settings.AI_MODEL,
        "status": "CONFIGURED" if ai_configured else "PENDING_CONFIGURATION",
    }

    resp_payload = {
        "status": "READY" if is_healthy else "NOT_READY",
        "service": "Finora Financial Engine",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
        "dependencies": dependencies,
        "database": "CONNECTED" if is_healthy and "UNHEALTHY" not in dependencies.get("database", "") else "DISCONNECTED",
        "worker_queue": queue_health,
        "ai_provider": dependencies["ai_provider"]
    }
    status_code = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=resp_payload)
