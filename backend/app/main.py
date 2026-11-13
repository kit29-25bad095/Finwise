from fastapi import FastAPI, status, Depends, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db_session
from app.api.v1 import auth, tenants, ingestion, reconciliation, leakage, forensic, dashboard

from app.workers.queue import check_worker_queue_health

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Deterministic Financial Reconciliation & Revenue Leakage Detection Engine for Indian D2C Enterprises.",
    version="1.0.0",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OWASP Security Headers Middleware
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
    return response

# Register API Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(tenants.router, prefix=settings.API_V1_STR)
app.include_router(ingestion.router, prefix=settings.API_V1_STR)
app.include_router(reconciliation.router, prefix=settings.API_V1_STR)
app.include_router(leakage.router, prefix=settings.API_V1_STR)
app.include_router(forensic.router, prefix=settings.API_V1_STR)
app.include_router(dashboard.router, prefix=settings.API_V1_STR)


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
def liveness():
    """Kubernetes / Cloud provider liveness probe."""
    return {"status": "ALIVE"}


@app.get("/health/ready", status_code=status.HTTP_200_OK, tags=["System"])
def readiness(db: Session = Depends(get_db_session)):
    """Kubernetes / Cloud provider readiness probe verifying database, queue, and AI dependencies."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unreachable: {str(e)}"
        )

    queue_health = check_worker_queue_health()
    if queue_health["status"].startswith("UNAVAILABLE") and not settings.WORKER_FALLBACK_SYNC:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis worker queue unavailable in strict production mode: {queue_health['status']}"
        )

    ai_configured = bool(settings.resolved_ai_api_key)

    return {
        "status": "READY",
        "database": "CONNECTED",
        "worker_queue": queue_health,
        "ai_provider": {
            "provider": settings.AI_PROVIDER,
            "model": settings.AI_MODEL,
            "status": "CONFIGURED" if ai_configured else "PENDING_CONFIGURATION"
        }
    }
