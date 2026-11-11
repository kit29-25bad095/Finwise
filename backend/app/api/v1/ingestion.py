import uuid
import csv
import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, desc

from app.core.database import get_db_session as get_db
from app.core.rbac import Role
from app.api.deps import get_current_user, get_current_tenant_membership, RoleChecker
from app.models.user import User
from app.models.tenant import TenantMembership
from app.models.ingestion import IngestionBatch, SourceRowError, IngestionStatus
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalBankTransaction,
)
from app.schemas.ingestion import (
    IngestionBatchResponse,
    SourceRowErrorResponse,
    ValidationReportResponse,
    CanonicalOrderResponse,
    CanonicalPaymentResponse,
    CanonicalSettlementResponse,
    CanonicalBankTransactionResponse,
)
from app.services.ingestion.ingestion_service import IngestionService
from app.workers.queue import enqueue_job
from app.workers.ingestion_tasks import process_ingestion_job

router = APIRouter(prefix="/ingestion", tags=["Data Ingestion & Normalization"])


@router.post(
    "/upload",
    response_model=IngestionBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload financial statement or order export CSV"
)
async def upload_csv_file(
    source_type: str = Form(..., description="SHOPIFY, RAZORPAY, or HDFC"),
    file: UploadFile = File(..., description="Source CSV document"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    tenant_id = membership.tenant_id

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty."
        )

    try:
        batch, is_duplicate = IngestionService.register_upload(
            db=db,
            tenant_id=tenant_id,
            user_id=current_user.id,
            source_type=source_type,
            filename=file.filename or "unknown.csv",
            file_bytes=file_bytes,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if is_duplicate:
        return batch

    # Enqueue background processing job
    enqueue_job(
        process_ingestion_job,
        str(batch.id),
        file_bytes
    )

    db.refresh(batch)
    return batch


@router.get(
    "/batches",
    response_model=List[IngestionBatchResponse],
    summary="List ingestion batches for tenant"
)
def list_ingestion_batches(
    source_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER, Role.AUDITOR])),
):
    query = select(IngestionBatch).where(IngestionBatch.tenant_id == membership.tenant_id)

    if source_type:
        query = query.where(IngestionBatch.source_type == source_type.upper().strip())
    if status_filter:
        query = query.where(IngestionBatch.status == status_filter.upper().strip())

    query = query.order_by(desc(IngestionBatch.created_at)).offset(skip).limit(limit)
    batches = db.execute(query).scalars().all()
    return batches


@router.get(
    "/batches/{batch_id}",
    response_model=IngestionBatchResponse,
    summary="Get ingestion batch details"
)
def get_ingestion_batch(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER, Role.AUDITOR])),
):
    batch = db.execute(
        select(IngestionBatch).where(
            and_(
                IngestionBatch.id == batch_id,
                IngestionBatch.tenant_id == membership.tenant_id
            )
        )
    ).scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion batch not found.")
    return batch


@router.get(
    "/batches/{batch_id}/errors",
    response_model=ValidationReportResponse,
    summary="Get row-level validation errors and summary"
)
def get_batch_validation_report(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER, Role.AUDITOR])),
):
    batch = db.execute(
        select(IngestionBatch).where(
            and_(
                IngestionBatch.id == batch_id,
                IngestionBatch.tenant_id == membership.tenant_id
            )
        )
    ).scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion batch not found.")

    errors = db.execute(
        select(SourceRowError)
        .where(
            and_(
                SourceRowError.batch_id == batch_id,
                SourceRowError.tenant_id == membership.tenant_id
            )
        )
        .order_by(SourceRowError.row_index)
    ).scalars().all()

    error_count_by_code = {}
    warning_count_by_code = {}
    for err in errors:
        if err.error_level == "ERROR":
            error_count_by_code[err.error_code] = error_count_by_code.get(err.error_code, 0) + 1
        elif err.error_level in ("WARNING", "DUPLICATE"):
            warning_count_by_code[err.error_code] = warning_count_by_code.get(err.error_code, 0) + 1

    return ValidationReportResponse(
        batch=batch,
        errors=errors,
        error_count_by_code=error_count_by_code,
        warning_count_by_code=warning_count_by_code,
    )


@router.get(
    "/batches/{batch_id}/errors/export",
    summary="Download row-level validation errors as CSV"
)
def export_batch_errors_csv(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER, Role.AUDITOR])),
):
    batch = db.execute(
        select(IngestionBatch).where(
            and_(
                IngestionBatch.id == batch_id,
                IngestionBatch.tenant_id == membership.tenant_id
            )
        )
    ).scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion batch not found.")

    errors = db.execute(
        select(SourceRowError)
        .where(
            and_(
                SourceRowError.batch_id == batch_id,
                SourceRowError.tenant_id == membership.tenant_id
            )
        )
        .order_by(SourceRowError.row_index)
    ).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Row Number", "Error Level", "Field Name", "Error Code", "Raw Value", "Error Message"])

    for err in errors:
        writer.writerow([
            err.row_index,
            err.error_level,
            err.field_name or "",
            err.error_code,
            err.raw_value or "",
            err.message
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=errors_batch_{batch_id}.csv"}
    )


@router.post(
    "/batches/{batch_id}/cancel",
    response_model=IngestionBatchResponse,
    summary="Cancel eligible pending ingestion batch"
)
def cancel_ingestion_batch(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    batch = db.execute(
        select(IngestionBatch).where(
            and_(
                IngestionBatch.id == batch_id,
                IngestionBatch.tenant_id == membership.tenant_id
            )
        )
    ).scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion batch not found.")

    if batch.status in (IngestionStatus.COMPLETED, IngestionStatus.COMPLETED_WITH_WARNINGS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel an already completed ingestion batch."
        )

    batch.status = IngestionStatus.CANCELLED
    db.commit()
    db.refresh(batch)
    return batch


# Canonical Queries
@router.get(
    "/canonical/orders",
    response_model=List[CanonicalOrderResponse],
    summary="List normalized canonical Shopify orders"
)
def list_canonical_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER, Role.AUDITOR])),
):
    orders = db.execute(
        select(CanonicalOrder)
        .where(CanonicalOrder.tenant_id == membership.tenant_id)
        .order_by(desc(CanonicalOrder.order_timestamp))
        .offset(skip)
        .limit(limit)
    ).scalars().all()
    return orders


@router.get(
    "/canonical/payments",
    response_model=List[CanonicalPaymentResponse],
    summary="List normalized canonical Razorpay payments"
)
def list_canonical_payments(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER, Role.AUDITOR])),
):
    payments = db.execute(
        select(CanonicalPayment)
        .where(CanonicalPayment.tenant_id == membership.tenant_id)
        .order_by(desc(CanonicalPayment.captured_at))
        .offset(skip)
        .limit(limit)
    ).scalars().all()
    return payments


@router.get(
    "/canonical/settlements",
    response_model=List[CanonicalSettlementResponse],
    summary="List normalized canonical Razorpay settlements"
)
def list_canonical_settlements(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER, Role.AUDITOR])),
):
    settlements = db.execute(
        select(CanonicalSettlement)
        .where(CanonicalSettlement.tenant_id == membership.tenant_id)
        .order_by(desc(CanonicalSettlement.settled_at))
        .offset(skip)
        .limit(limit)
    ).scalars().all()
    return settlements


@router.get(
    "/canonical/bank-transactions",
    response_model=List[CanonicalBankTransactionResponse],
    summary="List normalized canonical HDFC bank statement transactions"
)
def list_canonical_bank_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER, Role.AUDITOR])),
):
    txs = db.execute(
        select(CanonicalBankTransaction)
        .where(CanonicalBankTransaction.tenant_id == membership.tenant_id)
        .order_by(desc(CanonicalBankTransaction.transaction_date))
        .offset(skip)
        .limit(limit)
    ).scalars().all()
    return txs
