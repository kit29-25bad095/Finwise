import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db_session as get_db
from app.core.rbac import Role
from app.api.deps import (
    get_current_user,
    get_current_tenant_membership,
    RoleChecker,
)
from app.models.user import User
from app.models.tenant import TenantMembership
from app.schemas.dashboard import (
    DashboardOverviewResponse,
    LeakageFindingsResponse,
    ReviewQueueResponse,
    FeeAnalyticsResponse,
    AIInvestigationStatusResponse,
    AuditLogsResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard & Analytics"])


@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    summary="Get authoritative executive overview and 3-way financial reconciliation flow"
)
def get_dashboard_overview(
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    """
    Returns high-density financial metrics derived directly from authoritative
    canonical ledgers, active reconciliation runs, and fee overcharge detectors.
    """
    return DashboardService.get_dashboard_overview(db, membership.tenant_id)


@router.get(
    "/leakage-findings",
    response_model=LeakageFindingsResponse,
    summary="List all detected revenue leakage findings across the four core Phase 4 detectors"
)
def get_leakage_findings(
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    """
    Returns structured findings for:
    1. Missing Gateway Settlements
    2. Settlements Not Credited to Bank
    3. Contractual Fee Overcharges
    4. Duplicate or Unauthorized Refunds
    """
    return DashboardService.get_leakage_findings(db, membership.tenant_id)


@router.get(
    "/review-queue",
    response_model=ReviewQueueResponse,
    summary="List ambiguous, collision, or unallocated matches requiring human review"
)
def get_review_queue(
    status_filter: Optional[str] = Query(None, description="PENDING, APPROVED, REJECTED"),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    """
    Returns items in the financial review queue. Authorized Finance Managers and Admins
    can approve, reject, or manually allocate items via POST /reconciliation/matches/{id}/resolve.
    """
    return DashboardService.get_review_queue(db, membership.tenant_id, status_filter)


@router.get(
    "/fee-analytics",
    response_model=FeeAnalyticsResponse,
    summary="Contractual tariff comparison: expected MDR vs reported gateway fees"
)
def get_fee_analytics(
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    """
    Calculates expected MDR and GST per payment instrument according to the active versioned
    fee contract, comparing against gateway reported fees to surface systemic fee drift.
    """
    return DashboardService.get_fee_analytics(db, membership.tenant_id)


@router.get(
    "/ai-investigations",
    response_model=AIInvestigationStatusResponse,
    summary="Get status and investigation history from the AI forensic gateway"
)
def get_ai_investigations(
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    """
    Returns status of the AI investigation module. When Gemini API is not configured,
    gracefully presents pending configuration status without fabricating results.
    """
    return DashboardService.get_ai_investigation_status(db, membership.tenant_id)


@router.get(
    "/audit-logs",
    response_model=AuditLogsResponse,
    summary="List immutable system audit logs for tenant financial events"
)
def get_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    membership: TenantMembership = Depends(get_current_tenant_membership),
):
    """
    Returns immutable audit trail entries including entity mutations, reviewer rationales,
    IP addresses, and timestamps.
    """
    return DashboardService.get_audit_logs(db, membership.tenant_id, limit, offset)
