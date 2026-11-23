import uuid
import pytest
from sqlalchemy import text, Engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError, IntegrityError, DataError


def test_session_recovery_after_constraint_violation(pg_engine: Engine):
    """
    B6: Verify that when a transaction encounters a constraint violation in PostgreSQL,
    the session cleanly recovers after rollback and continues executing valid operations.
    """
    session = Session(bind=pg_engine)
    t_id = uuid.uuid4()
    slug = f"recover-{uuid.uuid4().hex[:8]}"

    try:
        # Step 1: Insert valid tenant
        session.execute(
            text("INSERT INTO tenants (id, name, slug, default_currency, is_active, created_at, updated_at) "
                 "VALUES (:id, 'Recovery Tenant', :slug, 'INR', true, NOW(), NOW())"),
            {"id": t_id, "slug": slug}
        )

        # Step 2: Trigger deliberate UniqueConstraint violation on slug
        with pytest.raises(IntegrityError):
            session.execute(
                text("INSERT INTO tenants (id, name, slug, default_currency, is_active, created_at, updated_at) "
                     "VALUES (:id, 'Duplicate Slug', :slug, 'INR', true, NOW(), NOW())"),
                {"id": uuid.uuid4(), "slug": slug}
            )

        # In PostgreSQL, an error puts the transaction into an aborted state
        # The session MUST be rolled back to recover
        session.rollback()

        # Step 3: Verify session recovered by executing a valid query
        current_time = session.scalar(text("SELECT NOW();"))
        assert current_time is not None, "Session failed to recover after rollback!"

    finally:
        session.close()


def test_connection_pool_recovery_under_failed_statements(pg_engine: Engine):
    """
    B6: Verify connection pool health when subjected to database errors.
    Connections returning from failed operations must be sanitized or reconnected cleanly.
    """
    with pg_engine.connect() as conn:
        # Cause intentional division by zero error
        with pytest.raises(DBAPIError):
            conn.execute(text("SELECT 1 / 0;"))

        # Re-use connection after rollback
        conn.rollback()
        res = conn.scalar(text("SELECT 42;"))
        assert res == 42, f"Connection failed to recover after error: {res}"


def test_numeric_overflow_rejected_safely(pg_engine: Engine):
    """
    B6: Verify that attempting to insert a number exceeding NUMERIC(18, 4) precision
    is rejected at the PostgreSQL level without corrupting the session.
    """
    session = Session(bind=pg_engine)
    try:
        # Number with 16 integer digits and 4 decimal digits fits (18 total),
        # but 20 integer digits should fail NUMERIC(18,4)
        with pytest.raises((DataError, DBAPIError)):
            session.execute(
                text("SELECT CAST(12345678901234567890.1234 AS NUMERIC(18,4));")
            )
        session.rollback()

        # Session remains healthy
        valid_val = session.scalar(text("SELECT CAST(12345.6789 AS NUMERIC(18,4));"))
        assert str(valid_val) == "12345.6789"

    finally:
        session.close()
