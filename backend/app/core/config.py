from decimal import Decimal
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Database: Supports PostgreSQL (postgresql://) and SQLite (sqlite://)
    DATABASE_URL: str = "sqlite:///./finora.db"
    SYNC_DATABASE_URL: str = "sqlite:///./finora.db"

    # Redis & Background Workers
    REDIS_URL: str = "redis://localhost:6379/0"
    WORKER_FALLBACK_SYNC: bool = True

    # AI Investigation Engine (Configurable)
    AI_PROVIDER: str = "gemini"
    AI_MODEL: str = "gemini-2.0-flash"
    AI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    AI_TEMPERATURE: float = 0.1
    AI_MAX_TOKENS: int = 2048

    @property
    def resolved_ai_api_key(self) -> Optional[str]:
        """
        Returns sanitized API key from GEMINI_API_KEY or AI_API_KEY.
        """
        key = self.GEMINI_API_KEY or self.AI_API_KEY
        if key and key.strip():
            return key.strip()
        return None

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

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    def validate_production_readiness(self) -> List[str]:
        issues = []
        if self.is_production:
            if "super-secure" in self.SECRET_KEY or len(self.SECRET_KEY) < 32:
                issues.append("Production environment must override default development SECRET_KEY.")
            if self.DATABASE_URL.startswith("sqlite"):
                issues.append("Production environment must use PostgreSQL (DATABASE_URL starting with postgresql://).")
        return issues


settings = Settings()
