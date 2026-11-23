import os
from typing import Generator
from urllib.parse import urlparse, urlunparse
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

# Read backend .env file directly to bypass root conftest sqlite override
_env_vars = dotenv_values(".env")
_raw_url = _env_vars.get("DATABASE_URL") or os.getenv("DATABASE_URL", "")
_parsed = urlparse(_raw_url)
PG_TEST_DATABASE_URL = urlunparse((
    _parsed.scheme if _parsed.scheme else "postgresql+psycopg2",
    _parsed.netloc,
    "/finora_test",
    _parsed.params,
    _parsed.query,
    _parsed.fragment,
))


@pytest.fixture(scope="session")
def pg_engine() -> Engine:
    """Session-scoped PostgreSQL engine connected strictly to finora_test."""
    engine = create_engine(
        PG_TEST_DATABASE_URL,
        poolclass=NullPool,  # Use NullPool for clean isolation during concurrency tests
    )
    with engine.connect() as conn:
        current_db = conn.scalar(text("SELECT current_database();"))
        if current_db != "finora_test":
            raise RuntimeError(
                f"ABSOLUTE SAFETY VIOLATION: Integration engine connected to '{current_db}' instead of 'finora_test'!"
            )
    return engine


@pytest.fixture(autouse=True)
def clean_database():
    """
    Override root conftest SQLite clean_database fixture to prevent
    unintended metadata drops or SQLite operations during integration tests.
    """
    yield


@pytest.fixture(autouse=True)
def pg_safety_check(pg_engine: Engine):
    """
    Autouse safety assertion executing before every integration test:
    guarantees the active database is strictly finora_test and user is finora_staging.
    """
    with pg_engine.connect() as conn:
        active_db = conn.scalar(text("SELECT current_database();"))
        active_user = conn.scalar(text("SELECT current_user;"))
        if active_db != "finora_test":
            raise RuntimeError(
                f"SAFETY CHECK FAILED: Expected database 'finora_test', got '{active_db}'"
            )
        if active_user != "finora_staging":
            raise RuntimeError(
                f"SAFETY CHECK FAILED: Expected user 'finora_staging', got '{active_user}'"
            )


@pytest.fixture
def pg_session(pg_engine: Engine) -> Generator[Session, None, None]:
    """
    Isolated PostgreSQL Session fixture running within an explicit transaction.
    Automatically rolls back after the test completes, guaranteeing zero data pollution.
    """
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
