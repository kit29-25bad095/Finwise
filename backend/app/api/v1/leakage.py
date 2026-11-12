import uuid
from typing import List, Optional, Dict, Any
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, desc, func

from app.core.database import get_db_session as get_db
from app.core.rbac import Role
from app.api.deps import get_current_user, get_current_tenant_membership, RoleChecker
from app.models.user import User
from app.models.tenant import TenantMembership
from app.models.leakage import (
    LeakageDetectionRun,
    LeakageException,
    LeakageRunException,
    LeakageExceptionEvidence,
    LeakageRunEvidence,
    LeakageExceptionReview,
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
    DetectionRunStatus,
)
from app.schemas.leakage import (
    DetectionRunCreate,
    DetectionRunResponse,
    LeakageExceptionResponse,
    LeakageRunExceptionResponse,
    EvidenceItemResponse,
    ExceptionReviewResponse,
    ExceptionReviewRequest,
    LeakageSummaryResponse,
)
from app.services.leakage.detection_engine import DetectionEngine
from app.workers.queue import enqueue_job
from app.workers.leakage_tasks import process_leakage_detection_job

router = APIRouter(prefix="/leakage", tags=["Revenue Leakage Detection Engine"])


# ---------------------------------------------------------------------------
# Leakage Detection Runs
# ---------------------------------------------------------------------------

@router.post(
    "/runs",
    response_model=DetectionRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger a deterministic revenue leakage detection run"
)
def create_detection_run(
    payload: DetectionRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    tenant_id = membership.tenant_id

    run = DetectionEngine.create_run(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        reconciliation_run_id=payload.reconciliation_run_id,
        parameters=payload.parameters
    )

    # Dispatch to background worker or sync fallback
    enqueue_job(process_leakage_detection_job, str(run.id))

    db.refresh(run)
    return run


@router.get(
    "/runs",
    response_model=List[DetectionRunResponse],
    summary="List leakage detection runs for tenant"
)
def list_detection_runs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    runs = db.execute(
        select(LeakageDetectionRun)
        .where(LeakageDetectionRun.tenant_id == membership.tenant_id)
        .order_by(desc(LeakageDetectionRun.run_number))
        .offset(skip)
        .limit(limit)
    ).scalars().all()
    return runs


@router.get(
    "/runs/{run_id}",
    response_model=DetectionRunResponse,
    summary="Get details of a specific detection run"
)
def get_detection_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    run = db.execute(
        select(LeakageDetectionRun).where(
            and_(
                LeakageDetectionRun.id == run_id,
                LeakageDetectionRun.tenant_id == membership.tenant_id
            )
        )
    ).scalars().first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leakage detection run not found."
        )
    return run


@router.get(
    "/runs/{run_id}/snapshots",
    response_model=List[LeakageRunExceptionResponse],
    summary="Get all point-in-time exception snapshots observed in a specific detection run"
)
def get_run_snapshots(
    run_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    run = db.execute(
        select(LeakageDetectionRun).where(
            and_(
                LeakageDetectionRun.id == run_id,
                LeakageDetectionRun.tenant_id == membership.tenant_id
            )
        )
    ).scalars().first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leakage detection run not found."
        )

    snapshots = db.execute(
        select(LeakageRunException)
        .where(
            and_(
                LeakageRunException.detection_run_id == run_id,
                LeakageRunException.tenant_id == membership.tenant_id
            )
        )
        .order_by(desc(LeakageRunException.observed_leakage_amount))
        .offset(skip)
        .limit(limit)
    ).scalars().all()
    return snapshots


# ---------------------------------------------------------------------------
# Leakage Exceptions
# ---------------------------------------------------------------------------

@router.get(
    "/exceptions",
    response_model=List[LeakageExceptionResponse],
    summary="List leakage exceptions with multi-factor filters"
)
def list_exceptions(
    detection_run_id: Optional[uuid.UUID] = Query(None),
    detector_type: Optional[str] = Query(None),
    exception_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = Query(None),
    min_amount: Optional[Decimal] = Query(None),
    max_amount: Optional[Decimal] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    stmt = select(LeakageException).where(LeakageException.tenant_id == membership.tenant_id)

    if detection_run_id:
        stmt = stmt.where(
            or_(
                LeakageException.detection_run_id == detection_run_id,
                LeakageException.latest_detection_run_id == detection_run_id,
                LeakageException.id.in_(
                    select(LeakageRunException.exception_id).where(
                        LeakageRunException.detection_run_id == detection_run_id
                    )
                )
            )
        )
    if detector_type:
        stmt = stmt.where(LeakageException.detector_type == detector_type.upper())
    if exception_type:
        stmt = stmt.where(LeakageException.exception_type == exception_type.upper())
    if status_filter:
        stmt = stmt.where(LeakageException.status == status_filter.upper())
    if severity:
        stmt = stmt.where(LeakageException.severity == severity.upper())
    if min_amount is not None:
        stmt = stmt.where(LeakageException.leakage_amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(LeakageException.leakage_amount <= max_amount)

    stmt = stmt.order_by(desc(LeakageException.leakage_amount), desc(LeakageException.created_at))
    stmt = stmt.offset(skip).limit(limit)

    return db.execute(stmt).scalars().all()


@router.get(
    "/exceptions/{exception_id}",
    response_model=LeakageExceptionResponse,
    summary="Get full details of a specific leakage exception"
)
def get_exception_details(
    exception_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    exc = db.execute(
        select(LeakageException).where(
            and_(
                LeakageException.id == exception_id,
                LeakageException.tenant_id == membership.tenant_id
            )
        )
    ).scalars().first()
    if not exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leakage exception not found."
        )
    return exc


@router.get(
    "/exceptions/{exception_id}/evidence",
    response_model=List[EvidenceItemResponse],
    summary="Retrieve all evidence records linked to a leakage exception"
)
def get_exception_evidence(
    exception_id: uuid.UUID,
    detection_run_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    exc = db.execute(
        select(LeakageException).where(
            and_(
                LeakageException.id == exception_id,
                LeakageException.tenant_id == membership.tenant_id
            )
        )
    ).scalars().first()
    if not exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leakage exception not found."
        )

    stmt = select(LeakageExceptionEvidence).where(
        and_(
            LeakageExceptionEvidence.exception_id == exception_id,
            LeakageExceptionEvidence.tenant_id == membership.tenant_id
        )
    )
    if detection_run_id:
        stmt = stmt.where(
            LeakageExceptionEvidence.id.in_(
                select(LeakageRunEvidence.evidence_id).where(
                    LeakageRunEvidence.detection_run_id == detection_run_id
                )
            )
        )
    evidence = db.execute(stmt.order_by(LeakageExceptionEvidence.created_at)).scalars().all()
    return evidence


@router.get(
    "/summary",
    response_model=LeakageSummaryResponse,
    summary="Aggregate leakage and potential recovery summary metrics"
)
def get_leakage_summary(
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    tenant_id = membership.tenant_id

    exceptions = db.execute(
        select(LeakageException).where(LeakageException.tenant_id == tenant_id)
    ).scalars().all()

    total_leakage = sum((e.leakage_amount for e in exceptions), Decimal("0.0000"))
    total_recovery = sum((e.recoverable_amount for e in exceptions), Decimal("0.0000"))

    open_count = sum(1 for e in exceptions if e.status == ExceptionStatus.OPEN.value)
    confirmed_count = sum(1 for e in exceptions if e.status == ExceptionStatus.CONFIRMED.value)
    disputed_count = sum(1 for e in exceptions if e.status == ExceptionStatus.DISPUTED.value)
    recovered_count = sum(1 for e in exceptions if e.status == ExceptionStatus.RECOVERED.value)
    resolved_count = sum(1 for e in exceptions if e.status == ExceptionStatus.RESOLVED.value)

    breakdown_detector: Dict[str, Dict[str, Any]] = {}
    for dtype in DetectorType:
        det_exceptions = [e for e in exceptions if e.detector_type == dtype.value]
        breakdown_detector[dtype.value] = {
            "count": len(det_exceptions),
            "total_leakage": str(sum((e.leakage_amount for e in det_exceptions), Decimal("0.0000"))),
            "total_recovery": str(sum((e.recoverable_amount for e in det_exceptions), Decimal("0.0000"))),
        }

    breakdown_severity: Dict[str, int] = {
        sev.value: sum(1 for e in exceptions if e.severity == sev.value)
        for sev in ExceptionSeverity
    }

    return LeakageSummaryResponse(
        total_leakage_amount=total_leakage,
        total_potential_recovery=total_recovery,
        total_exceptions=len(exceptions),
        open_exceptions=open_count,
        confirmed_exceptions=confirmed_count,
        disputed_exceptions=disputed_count,
        recovered_exceptions=recovered_count,
        resolved_exceptions=resolved_count,
        breakdown_by_detector=breakdown_detector,
        breakdown_by_severity=breakdown_severity
    )


# ---------------------------------------------------------------------------
# Human Review & Resolution Workflow
# ---------------------------------------------------------------------------

@router.post(
    "/exceptions/{exception_id}/review",
    response_model=LeakageExceptionResponse,
    summary="Submit a human review action on a leakage exception"
)
def review_exception(
    exception_id: uuid.UUID,
    payload: ExceptionReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    try:
        updated_exc = DetectionEngine.review_exception(
            db=db,
            exception_id=exception_id,
            tenant_id=membership.tenant_id,
            reviewer_id=current_user.id,
            action=payload.action,
            notes=payload.notes
        )
        return updated_exc
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.post(
    "/exceptions/{exception_id}/resolve",
    response_model=LeakageExceptionResponse,
    summary="Resolve a confirmed or disputed leakage exception"
)
def resolve_exception(
    exception_id: uuid.UUID,
    payload: Optional[ExceptionReviewRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    action = payload.action if payload and payload.action else "RESOLVE"
    notes = payload.notes if payload else "Resolved by finance operator."
    try:
        updated_exc = DetectionEngine.review_exception(
            db=db,
            exception_id=exception_id,
            tenant_id=membership.tenant_id,
            reviewer_id=current_user.id,
            action=action,
            notes=notes
        )
        return updated_exc
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
