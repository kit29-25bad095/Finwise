import uuid
from decimal import Decimal
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError


def _seed_pg_tenant_and_investigation(pg_session: Session):
    t_id = uuid.uuid4()
    run_id = uuid.uuid4()
    exc_id = uuid.uuid4()
    inv_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Tenant
    pg_session.execute(
        text("INSERT INTO tenants (id, name, slug, default_currency, is_active, created_at, updated_at) "
             "VALUES (:id, 'FK Test Tenant', :slug, 'INR', true, NOW(), NOW())"),
        {"id": t_id, "slug": f"fk-{uuid.uuid4().hex[:8]}"}
    )

    # Detection Run
    pg_session.execute(
        text("INSERT INTO leakage_detection_runs (id, tenant_id, run_number, status, created_at, updated_at) "
             "VALUES (:id, :t_id, 1, 'COMPLETED', NOW(), NOW())"),
        {"id": run_id, "t_id": t_id}
    )

    # Exception
    pg_session.execute(
        text("""
            INSERT INTO leakage_exceptions (
                id, tenant_id, detection_run_id, latest_detection_run_id, detector_type,
                exception_type, status, severity, severity_reason, source_entity_type,
                source_entity_id, source_reference, gateway_name, expected_amount,
                actual_amount, leakage_amount, recoverable_amount, currency, explanation,
                created_at, updated_at
            ) VALUES (
                :id, :t_id, :run_id, :run_id, 'FEE_OVERCHARGE',
                'FEE_OVERCHARGE', 'OPEN', 'HIGH', 'Overcharge detected', 'canonical_payments',
                :src_id, 'ref_001', 'RAZORPAY', 20.0000,
                25.0000, 5.0000, 5.0000, 'INR', 'Variance explanation',
                NOW(), NOW()
            )
        """),
        {"id": exc_id, "t_id": t_id, "run_id": run_id, "src_id": uuid.uuid4()}
    )

    # Investigation
    pg_session.execute(
        text("""
            INSERT INTO forensic_investigations (
                id, tenant_id, exception_id, detection_run_id, status, conclusion,
                confidence, summary, evidence_bundle_fingerprint, evidence_bundle_snapshot,
                model_provider, model_name, prompt_version, schema_version,
                created_at, updated_at
            ) VALUES (
                :id, :t_id, :exc_id, :run_id, 'COMPLETED', 'SUPPORTED',
                'HIGH', 'Investigation summary', :fingerprint, '{}'::json,
                'mock', 'mock-v1', 'v1.0', 'v1.0',
                NOW(), NOW()
            )
        """),
        {"id": inv_id, "t_id": t_id, "exc_id": exc_id, "run_id": run_id, "fingerprint": "a" * 64}
    )

    return t_id, run_id, exc_id, inv_id


def test_tenant_deletion_blocked_by_forensic_investigation_fk(pg_session: Session):
    """B3: Verify raw SQL DELETE of Tenant is blocked by PostgreSQL RESTRICT foreign key on forensic_investigations."""
    t_id, run_id, exc_id, inv_id = _seed_pg_tenant_and_investigation(pg_session)

    with pytest.raises(IntegrityError) as exc_info:
        pg_session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": t_id})

    err = str(exc_info.value).lower()
    assert "foreign key constraint" in err or "violates foreign key" in err
    assert "forensic_investigations" in err or "fk" in err


def test_exception_deletion_blocked_by_investigation_fk(pg_session: Session):
    """B3: Verify raw SQL DELETE of LeakageException is blocked by RESTRICT constraint on forensic_investigations."""
    t_id, run_id, exc_id, inv_id = _seed_pg_tenant_and_investigation(pg_session)

    with pytest.raises(IntegrityError) as exc_info:
        pg_session.execute(text("DELETE FROM leakage_exceptions WHERE id = :id"), {"id": exc_id})

    err = str(exc_info.value).lower()
    assert "foreign key constraint" in err or "violates foreign key" in err


def test_investigation_deletion_blocked_by_claim_draft_fk(pg_session: Session):
    """B3: Verify raw SQL DELETE of ForensicInvestigation is blocked by RESTRICT constraint on forensic_claim_drafts."""
    t_id, run_id, exc_id, inv_id = _seed_pg_tenant_and_investigation(pg_session)
    draft_id = uuid.uuid4()

    # Insert Claim Draft referencing Investigation
    pg_session.execute(
        text("""
            INSERT INTO forensic_claim_drafts (
                id, tenant_id, exception_id, investigation_id, detection_run_id,
                draft_number, status, dispute_amount, currency, target_entity,
                target_reference, claim_summary, supporting_facts, evidence_references,
                human_review_status, disclaimer, created_at, updated_at
            ) VALUES (
                :id, :t_id, :exc_id, :inv_id, :run_id,
                1, 'DRAFT', 5.0000, 'INR', 'RAZORPAY',
                'ref_001', 'Claim summary', '[]'::json, '[]'::json,
                'PENDING_HUMAN_REVIEW', 'disclaimer', NOW(), NOW()
            )
        """),
        {"id": draft_id, "t_id": t_id, "exc_id": exc_id, "inv_id": inv_id, "run_id": run_id}
    )

    with pytest.raises(IntegrityError) as exc_info:
        pg_session.execute(text("DELETE FROM forensic_investigations WHERE id = :id"), {"id": inv_id})

    err = str(exc_info.value).lower()
    assert "foreign key constraint" in err or "violates foreign key" in err
    assert "forensic_claim_drafts" in err or "fk" in err
