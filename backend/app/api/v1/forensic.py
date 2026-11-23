import uuid
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db_session as get_db
from app.core.rbac import Role
from app.api.deps import get_current_user, get_current_tenant_membership, RoleChecker
from app.models.user import User
from app.models.tenant import TenantMembership
from app.models.forensic import (
    ForensicInvestigation,
    ForensicClaimDraft,
    InvestigationStatus,
)
from app.schemas.forensic import (
    InvestigationCreateRequest,
    InvestigationResponse,
    EvidenceBundleResponse,
    ClaimDraftCreateRequest,
    ClaimDraftResponse,
)
from app.services.forensics.investigation_service import ForensicInvestigationService
from app.services.forensics.claim_draft_service import ClaimDraftService
from app.services.forensics.monitoring import ForensicMetricsCollector
from app.services.forensics.exceptions import (
    ResourceNotFoundError,
    InvalidInvestigationStateError,
    TenantMismatchError,
    EvidenceIntegrityError,
)
from app.workers.queue import enqueue_job
from app.workers.forensic_tasks import process_forensic_investigation_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forensics", tags=["AI Forensic Investigator & Root Cause Analysis"])


# ---------------------------------------------------------------------------
# Investigation Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/exceptions/{exception_id}/investigations",
    response_model=InvestigationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger or enqueue an AI forensic root-cause investigation for a leakage exception"
)
def create_investigation(
    exception_id: uuid.UUID,
    payload: InvestigationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    try:
        investigation = ForensicInvestigationService.create_investigation(
            db=db,
            tenant_id=membership.tenant_id,
            exception_id=exception_id,
            user_id=current_user.id,
            idempotency_key=payload.idempotency_key,
            force_refresh=payload.force_refresh,
        )

        # If investigation is freshly created in PENDING status, dispatch to worker
        if investigation.status == InvestigationStatus.PENDING.value:
            try:
                enqueue_job(process_forensic_investigation_job, str(investigation.id))
            except Exception as q_err:
                logger.exception("Failed to dispatch investigation %s to background queue", investigation.id)
                investigation.status = InvestigationStatus.FAILED.value
                investigation.error_message = "Background worker queue dispatch failure."
                db.commit()
                db.refresh(investigation)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Background worker queue is currently unavailable."
                )

            # If queue dispatch succeeded, mark outbox event published if found
            try:
                from app.models.forensic import ForensicDispatchOutbox, OutboxEventType
                from app.services.forensics.outbox_service import TransactionalOutboxService
                idempotency_key = f"{investigation.id}:{OutboxEventType.INVESTIGATION_DISPATCH.value}:initial"
                stmt_evt = select(ForensicDispatchOutbox).where(ForensicDispatchOutbox.idempotency_key == idempotency_key)
                evt = db.execute(stmt_evt).scalar_one_or_none()
                if evt:
                    TransactionalOutboxService.mark_event_published(db, evt.id)
            except Exception as outbox_err:
                logger.warning("Could not mark outbox event published: %s", outbox_err)

            db.refresh(investigation)

        return investigation
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error initiating forensic investigation for exception %s", exception_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate investigation due to an internal server error."
        )


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationResponse,
    summary="Retrieve details and forensic findings of a specific investigation"
)
def get_investigation(
    investigation_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    try:
        return ForensicInvestigationService.get_investigation(
            db=db,
            tenant_id=membership.tenant_id,
            investigation_id=investigation_id
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/exceptions/{exception_id}/investigations",
    response_model=List[InvestigationResponse],
    summary="List all historical forensic investigations for an exception"
)
def list_investigations_for_exception(
    exception_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    try:
        return ForensicInvestigationService.list_investigations_for_exception(
            db=db,
            tenant_id=membership.tenant_id,
            exception_id=exception_id,
            skip=skip,
            limit=limit,
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/investigations/{investigation_id}/evidence",
    response_model=EvidenceBundleResponse,
    summary="Retrieve the immutable evidence bundle snapshot evaluated in an investigation"
)
def get_investigation_evidence_bundle(
    investigation_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    try:
        inv = ForensicInvestigationService.get_investigation(
            db=db,
            tenant_id=membership.tenant_id,
            investigation_id=investigation_id
        )
        return EvidenceBundleResponse(
            evidence_bundle_fingerprint=inv.evidence_bundle_fingerprint,
            bundle_snapshot=inv.evidence_bundle_snapshot
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# Claim Draft Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/investigations/{investigation_id}/claim-drafts",
    response_model=ClaimDraftResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a human-reviewable dispute claim draft from verified investigation facts"
)
def create_claim_draft(
    investigation_id: uuid.UUID,
    payload: ClaimDraftCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    try:
        draft = ClaimDraftService.create_claim_draft(
            db=db,
            tenant_id=membership.tenant_id,
            investigation_id=investigation_id,
            user_id=current_user.id,
            target_entity=payload.target_entity,
            notes=payload.notes,
        )
        return draft
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidInvestigationStateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error generating claim draft for investigation %s", investigation_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate claim draft due to an internal server error."
        )


@router.get(
    "/claim-drafts/{draft_id}",
    response_model=ClaimDraftResponse,
    summary="Retrieve details of a dispute claim draft"
)
def get_claim_draft(
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    try:
        return ClaimDraftService.get_claim_draft(
            db=db,
            tenant_id=membership.tenant_id,
            draft_id=draft_id
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# Operational Metrics Endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/metrics",
    summary="Get tenant-scoped operational metrics for AI forensic investigations (Admin / Finance Manager / Auditor)"
)
def get_forensic_metrics(
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER, Role.AUDITOR])),
):
    return ForensicMetricsCollector.get_tenant_metrics_summary(str(membership.tenant_id))
