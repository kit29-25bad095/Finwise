import uuid
from typing import List, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, desc

from app.core.database import get_db_session as get_db
from app.core.rbac import Role
from app.api.deps import get_current_user, get_current_tenant_membership, RoleChecker
from app.models.user import User
from app.models.tenant import TenantMembership
from app.models.reconciliation import (
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationAllocation,
    FeeContract,
    FeeScheduleTier,
    ReconciliationStatus,
    MatchClassification,
    MatchType,
    ReviewStatus,
)
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalBankTransaction,
)
from app.schemas.reconciliation import (
    ReconciliationRunCreate,
    ReconciliationRunResponse,
    ReconciliationMatchResponse,
    ReconciliationAllocationResponse,
    ReconciliationSummaryResponse,
    MatchResolutionRequest,
    UnmatchedEntitiesResponse,
    FeeContractCreate,
    FeeContractResponse,
)
from app.services.reconciliation.reconciliation_service import ReconciliationService
from app.workers.queue import enqueue_job
from app.workers.reconciliation_tasks import process_reconciliation_job

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation Engine"])


# ---------------------------------------------------------------------------
# Fee Contracts Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/contracts",
    response_model=FeeContractResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or version a payment gateway fee contract"
)
def create_fee_contract(
    payload: FeeContractCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    tenant_id = membership.tenant_id

    # Deactivate existing active contracts for this gateway if active
    existing_active = db.execute(
        select(FeeContract).where(
            and_(
                FeeContract.tenant_id == tenant_id,
                FeeContract.gateway_name == payload.gateway_name.upper(),
                FeeContract.is_active == True
            )
        )
    ).scalars().all()
    next_version = len(existing_active) + 1
    for c in existing_active:
        c.is_active = False

    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name=payload.gateway_name.upper(),
        contract_name=payload.contract_name,
        version=next_version,
        is_active=True,
        start_date=payload.start_date,
        end_date=payload.end_date,
        gst_rate=payload.gst_rate,
        chargeback_dispute_fee=payload.chargeback_dispute_fee,
        rolling_reserve_percentage=payload.rolling_reserve_percentage,
        rolling_reserve_hold_days=payload.rolling_reserve_hold_days,
        retain_mdr_on_refund=payload.retain_mdr_on_refund,
        instant_refund_flat_fee=payload.instant_refund_flat_fee,
        instant_refund_percentage_fee=payload.instant_refund_percentage_fee,
    )
    db.add(contract)
    db.flush()

    for tier_in in payload.tiers:
        tier = FeeScheduleTier(
            contract_id=contract.id,
            tenant_id=tenant_id,
            instrument_type=tier_in.instrument_type.upper(),
            percentage_rate=tier_in.percentage_rate,
            fixed_fee_per_txn=tier_in.fixed_fee_per_txn,
            min_fee_cap=tier_in.min_fee_cap,
            max_fee_cap=tier_in.max_fee_cap,
        )
        db.add(tier)

    db.commit()
    db.refresh(contract)
    return contract


@router.get(
    "/contracts",
    response_model=List[FeeContractResponse],
    summary="List fee contracts for tenant"
)
def list_fee_contracts(
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    contracts = db.execute(
        select(FeeContract).where(FeeContract.tenant_id == membership.tenant_id).order_by(desc(FeeContract.created_at))
    ).scalars().all()
    return contracts


# ---------------------------------------------------------------------------
# Reconciliation Runs Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/runs",
    response_model=ReconciliationRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger a deterministic 3-way reconciliation run"
)
def trigger_reconciliation_run(
    payload: Optional[ReconciliationRunCreate] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    tenant_id = membership.tenant_id
    params_dict = payload.parameters.model_dump() if (payload and payload.parameters) else {}

    run = ReconciliationService.create_run(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        parameters=params_dict
    )

    # Dispatch to background worker or sync fallback
    enqueue_job(process_reconciliation_job, str(run.id))

    db.refresh(run)
    return run


@router.get(
    "/runs",
    response_model=List[ReconciliationRunResponse],
    summary="List reconciliation runs for tenant"
)
def list_reconciliation_runs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    runs = db.execute(
        select(ReconciliationRun)
        .where(ReconciliationRun.tenant_id == membership.tenant_id)
        .order_by(desc(ReconciliationRun.run_number))
        .offset(skip)
        .limit(limit)
    ).scalars().all()
    return runs


@router.get(
    "/runs/{run_id}",
    response_model=ReconciliationRunResponse,
    summary="Get detailed reconciliation run metrics and status"
)
def get_reconciliation_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    run = db.execute(
        select(ReconciliationRun).where(
            and_(
                ReconciliationRun.id == run_id,
                ReconciliationRun.tenant_id == membership.tenant_id
            )
        )
    ).scalars().first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation run not found")
    return run


@router.get(
    "/runs/{run_id}/matches",
    response_model=List[ReconciliationMatchResponse],
    summary="List matches produced by a reconciliation run"
)
def list_run_matches(
    run_id: uuid.UUID,
    classification: Optional[str] = Query(None, description="EXACT_MATCH, PARTIAL_MATCH, AGGREGATED_MATCH, AMBIGUOUS_MATCH, UNRESOLVED..."),
    match_type: Optional[str] = Query(None, description="ORDER_TO_PAYMENT, SETTLEMENT_TO_BANK, THREE_WAY"),
    review_status: Optional[str] = Query(None, description="PENDING_REVIEW, APPROVED, REJECTED, RESOLVED, NOT_REQUIRED"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    # Verify run exists for tenant
    run = db.execute(
        select(ReconciliationRun).where(
            and_(
                ReconciliationRun.id == run_id,
                ReconciliationRun.tenant_id == membership.tenant_id
            )
        )
    ).scalars().first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation run not found")

    conditions = [
        ReconciliationMatch.run_id == run_id,
        ReconciliationMatch.tenant_id == membership.tenant_id
    ]
    if classification:
        conditions.append(ReconciliationMatch.classification == classification.upper())
    if match_type:
        conditions.append(ReconciliationMatch.match_type == match_type.upper())
    if review_status:
        conditions.append(ReconciliationMatch.review_status == review_status.upper())

    matches = db.execute(
        select(ReconciliationMatch)
        .where(and_(*conditions))
        .order_by(ReconciliationMatch.pass_number, desc(ReconciliationMatch.confidence_score))
        .offset(skip)
        .limit(limit)
    ).scalars().all()
    return matches


@router.get(
    "/runs/{run_id}/ambiguous",
    response_model=List[ReconciliationMatchResponse],
    summary="List ambiguous matches and bound-exceeded candidates requiring review"
)
def list_ambiguous_matches(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    run = db.execute(
        select(ReconciliationRun).where(
            and_(
                ReconciliationRun.id == run_id,
                ReconciliationRun.tenant_id == membership.tenant_id
            )
        )
    ).scalars().first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation run not found")

    matches = db.execute(
        select(ReconciliationMatch).where(
            and_(
                ReconciliationMatch.run_id == run_id,
                ReconciliationMatch.tenant_id == membership.tenant_id,
                or_(
                    ReconciliationMatch.classification == MatchClassification.AMBIGUOUS_MATCH.value,
                    ReconciliationMatch.classification == MatchClassification.AMBIGUOUS_AGGREGATION_COLLISION.value,
                    ReconciliationMatch.classification == MatchClassification.UNRESOLVED_SUBSET_BOUND_EXCEEDED.value,
                    ReconciliationMatch.review_status == ReviewStatus.PENDING_REVIEW.value
                )
            )
        ).order_by(desc(ReconciliationMatch.created_at))
    ).scalars().all()
    return matches


@router.get(
    "/runs/{run_id}/allocations",
    response_model=List[ReconciliationAllocationResponse],
    summary="List fine-grained double-entry allocations ledger for a run"
)
def list_run_allocations(
    run_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    run = db.execute(
        select(ReconciliationRun).where(
            and_(
                ReconciliationRun.id == run_id,
                ReconciliationRun.tenant_id == membership.tenant_id
            )
        )
    ).scalars().first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation run not found")

    allocations = db.execute(
        select(ReconciliationAllocation)
        .where(
            and_(
                ReconciliationAllocation.run_id == run_id,
                ReconciliationAllocation.tenant_id == membership.tenant_id
            )
        )
        .order_by(desc(ReconciliationAllocation.created_at))
        .offset(skip)
        .limit(limit)
    ).scalars().all()
    return allocations


@router.get(
    "/runs/{run_id}/summary",
    response_model=ReconciliationSummaryResponse,
    summary="Get executive summary of three-way financial reconciliation run"
)
def get_reconciliation_summary(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    run = db.execute(
        select(ReconciliationRun).where(
            and_(
                ReconciliationRun.id == run_id,
                ReconciliationRun.tenant_id == membership.tenant_id
            )
        )
    ).scalars().first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation run not found")

    order_rate = (
        (Decimal(run.matched_orders_count) / Decimal(run.total_orders_evaluated) * Decimal("100")).quantize(Decimal("0.01"))
        if run.total_orders_evaluated > 0 else Decimal("0.00")
    )
    settle_rate = (
        (Decimal(run.matched_settlements_count) / Decimal(run.total_settlements_evaluated) * Decimal("100")).quantize(Decimal("0.01"))
        if run.total_settlements_evaluated > 0 else Decimal("0.00")
    )

    return ReconciliationSummaryResponse(
        run_id=run.id,
        run_number=run.run_number,
        status=ReconciliationStatus(run.status),
        is_active=run.is_active,
        total_expected_revenue=run.total_order_amount,
        total_captured_revenue=run.total_captured_amount,
        total_settled_revenue=run.total_settled_amount,
        total_bank_credited_revenue=run.total_matched_bank_amount,
        order_to_payment_match_rate=order_rate,
        settlement_to_bank_match_rate=settle_rate,
        total_discrepancy_amount=run.total_discrepancy_amount,
        unmatched_orders_count=run.unmatched_orders_count,
        unmatched_payments_count=run.unmatched_payments_count,
        unmatched_settlements_count=run.unmatched_settlements_count,
        unmatched_bank_txs_count=run.unmatched_bank_txs_count,
        ambiguous_matches_count=run.ambiguous_matches_count,
        unresolved_count=run.unresolved_count,
        total_fee_drift=run.total_fee_drift_amount
    )


@router.get(
    "/runs/{run_id}/unmatched",
    response_model=UnmatchedEntitiesResponse,
    summary="List unmatched canonical entities for a run"
)
def get_unmatched_entities(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    tenant_id = membership.tenant_id
    run = db.execute(
        select(ReconciliationRun).where(
            and_(
                ReconciliationRun.id == run_id,
                ReconciliationRun.tenant_id == tenant_id
            )
        )
    ).scalars().first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation run not found")

    unmatched_matches = db.execute(
        select(ReconciliationMatch).where(
            and_(
                ReconciliationMatch.run_id == run_id,
                ReconciliationMatch.tenant_id == tenant_id,
                ReconciliationMatch.classification == MatchClassification.UNMATCHED.value
            )
        )
    ).scalars().all()

    unmatched_orders = []
    unmatched_payments = []
    unmatched_settlements = []
    unmatched_bank_txs = []

    for m in unmatched_matches:
        if m.order_id:
            ord_entity = db.get(CanonicalOrder, m.order_id)
            if ord_entity:
                unmatched_orders.append({
                    "order_id": str(ord_entity.id),
                    "order_reference": ord_entity.order_reference,
                    "gross_amount": str(ord_entity.gross_amount),
                    "order_timestamp": ord_entity.order_timestamp.isoformat()
                })
        elif m.payment_id:
            pay_entity = db.get(CanonicalPayment, m.payment_id)
            if pay_entity:
                unmatched_payments.append({
                    "payment_id": str(pay_entity.id),
                    "gateway_payment_id": pay_entity.gateway_payment_id,
                    "captured_amount": str(pay_entity.captured_amount),
                    "unallocated_balance": str(pay_entity.unallocated_balance),
                    "captured_at": pay_entity.captured_at.isoformat()
                })
        elif m.settlement_id:
            setl_entity = db.get(CanonicalSettlement, m.settlement_id)
            if setl_entity:
                unmatched_settlements.append({
                    "settlement_id": str(setl_entity.id),
                    "settlement_reference": setl_entity.settlement_reference,
                    "utr_number": setl_entity.utr_number,
                    "net_settlement_amount": str(setl_entity.net_settlement_amount),
                    "unallocated_balance": str(setl_entity.unallocated_balance),
                    "settled_at": setl_entity.settled_at.isoformat()
                })
        elif m.bank_transaction_id:
            bank_entity = db.get(CanonicalBankTransaction, m.bank_transaction_id)
            if bank_entity:
                unmatched_bank_txs.append({
                    "bank_transaction_id": str(bank_entity.id),
                    "bank_reference": bank_entity.bank_reference,
                    "extracted_utr": bank_entity.extracted_utr,
                    "credit_amount": str(bank_entity.credit_amount),
                    "unallocated_balance": str(bank_entity.unallocated_balance),
                    "transaction_date": str(bank_entity.transaction_date)
                })

    return UnmatchedEntitiesResponse(
        run_id=run.id,
        unmatched_orders=unmatched_orders,
        unmatched_payments=unmatched_payments,
        unmatched_settlements=unmatched_settlements,
        unmatched_bank_transactions=unmatched_bank_txs
    )


# ---------------------------------------------------------------------------
# Human Review & Resolution Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/matches/{match_id}/resolve",
    response_model=ReconciliationMatchResponse,
    summary="Human review resolution of an ambiguous or exception match"
)
def resolve_reconciliation_match(
    match_id: uuid.UUID,
    payload: MatchResolutionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN, Role.FINANCE_MANAGER])),
):
    tenant_id = membership.tenant_id
    try:
        resolved_match = ReconciliationService.resolve_match(
            db=db,
            match_id=match_id,
            tenant_id=tenant_id,
            user_id=current_user.id,
            action=payload.action,
            notes=payload.notes,
            target_entity_id=payload.target_entity_id,
            manual_amount=payload.allocated_amount
        )
        return resolved_match
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
