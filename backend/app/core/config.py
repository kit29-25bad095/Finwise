import os
from decimal import Decimal
from typing import Any, List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    PROJECT_NAME: str = "Finora — Financial Reconciliation & Revenue Leakage Engine"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # Security & JWT
    SECRET_KEY: str = "finora-super-secure-production-ready-jwt-secret-key-32-chars-min"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB

    # Private File Storage & Retention
    STORAGE_DIR: str = "./storage"
    FILE_RETENTION_DAYS: int = 2555  # 7 years statutory financial record retention

    # Database: Supports PostgreSQL (postgresql://) and SQLite (sqlite://)
    DATABASE_URL: str = "sqlite:///./finora.db"
    SYNC_DATABASE_URL: str = "sqlite:///./finora.db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True
    DB_ECHO: bool = False
    DB_SSL_MODE: Optional[str] = None

    # Redis & Background Workers
    REDIS_URL: str = "redis://localhost:6379/0"
    WORKER_FALLBACK_SYNC: bool = True

    @model_validator(mode="before")
    @classmethod
    def populate_ai_api_key(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "AI_API_KEY" not in data and "GEMINI_API_KEY" in data:
                data["AI_API_KEY"] = data["GEMINI_API_KEY"]
            elif "AI_API_KEY" not in data and os.environ.get("GEMINI_API_KEY"):
                data["AI_API_KEY"] = os.environ.get("GEMINI_API_KEY")
        return data

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.ENVIRONMENT.lower() == "production":
            if self.WORKER_FALLBACK_SYNC:
                raise ValueError(
                    "WORKER_FALLBACK_SYNC must be False in production to prevent silent synchronous "
                    "execution of expensive AI investigations when Redis is unavailable."
                )
            if not self.SECRET_KEY or len(self.SECRET_KEY) < 32 or "super-secure" in self.SECRET_KEY:
                raise ValueError(
                    "A non-default SECRET_KEY of at least 32 characters is required in production."
                )
            if "sqlite" in self.DATABASE_URL.lower() or "sqlite" in self.SYNC_DATABASE_URL.lower():
                raise ValueError(
                    "PostgreSQL is required in production; SQLite is strictly prohibited."
                )
            if self.AI_PROVIDER.lower() == "gemini" and not (self.AI_API_KEY and self.AI_API_KEY.strip()):
                raise ValueError(
                    "AI_API_KEY is required in production when AI_PROVIDER is 'gemini'."
                )
            self.COOKIE_SECURE = True
            if "*" in self.BACKEND_CORS_ORIGINS:
                raise ValueError("Wildcard '*' CORS origin is strictly prohibited in production.")
        return self

    # AI Investigation Engine (Configurable)
    AI_PROVIDER: str = "gemini"
    AI_MODEL: str = "gemini-3.5-flash-lite"
    AI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    AI_TEMPERATURE: float = 0.1
    AI_MAX_TOKENS: int = 2048

    # Forensic Investigation Lease & Worker Recovery
    FORENSIC_LEASE_DURATION_SECONDS: int = 300
    FORENSIC_HEARTBEAT_INTERVAL_SECONDS: int = 60
    FORENSIC_MAX_EXECUTION_ATTEMPTS: int = 3
    FORENSIC_OUTBOX_BATCH_SIZE: int = 50
    FORENSIC_OUTBOX_LEASE_SECONDS: int = 60

    # Financial Calculation Defaults
    DEFAULT_CURRENCY: str = "INR"
    DEFAULT_FEE_OVERCHARGE_TOLERANCE: Decimal = Decimal("0.05")
    DEFAULT_SETTLEMENT_CUTOFF_TIME: str = "23:00"
    DEFAULT_MAX_KNAPSACK_BOUND: int = 5

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3100",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3100",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]


settings = Settings()
