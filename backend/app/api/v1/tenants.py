import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.rbac import Role, Permission
from app.models.user import User
from app.models.tenant import Tenant, TenantMembership
from app.schemas.tenant import (
    TenantRead,
    TenantUpdate,
    TenantMembershipRead,
    AddMemberRequest
)
from app.services.tenant_service import TenantService
from app.api.deps import (
    get_current_user,
    get_current_tenant_membership,
    RoleChecker,
    PermissionChecker
)

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get("/", response_model=List[TenantMembershipRead])
def list_user_tenants(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
    memberships = TenantService.get_user_memberships(session, current_user.id)
    return [TenantMembershipRead.model_validate(m) for m in memberships]


@router.get("/{tenant_id}", response_model=TenantRead)
def get_tenant_details(
    tenant_id: uuid.UUID,
    membership: TenantMembership = Depends(get_current_tenant_membership),
    session: Session = Depends(get_db_session)
):
    if membership.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to tenant environment."
        )

    tenant = TenantService.get_tenant_by_id(session, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found."
        )
    return TenantRead.model_validate(tenant)


@router.patch("/{tenant_id}", response_model=TenantRead)
def update_tenant_settings(
    tenant_id: uuid.UUID,
    update_data: TenantUpdate,
    request: Request,
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN])),
    session: Session = Depends(get_db_session)
):
    if membership.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to tenant environment."
        )

    client_ip = request.client.host if request.client else None
    return TenantService.update_tenant(
        session=session,
        tenant_id=tenant_id,
        performed_by_id=membership.user_id,
        update_data=update_data,
        ip_address=client_ip
    )


@router.delete("/{tenant_id}", response_model=TenantRead)
def deactivate_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN])),
    session: Session = Depends(get_db_session)
):
    if membership.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to tenant environment."
        )

    client_ip = request.client.host if request.client else None
    return TenantService.deactivate_tenant(
        session=session,
        tenant_id=tenant_id,
        performed_by_id=membership.user_id,
        user_rationale="Soft-deactivation requested via API",
        ip_address=client_ip
    )


@router.post("/{tenant_id}/members", response_model=TenantMembershipRead, status_code=status.HTTP_201_CREATED)
def add_tenant_member(
    tenant_id: uuid.UUID,
    req: AddMemberRequest,
    request: Request,
    membership: TenantMembership = Depends(RoleChecker([Role.ADMIN])),
    session: Session = Depends(get_db_session)
):
    if membership.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to tenant environment."
        )

    client_ip = request.client.host if request.client else None
    new_mem = TenantService.add_member(
        session=session,
        tenant_id=tenant_id,
        performed_by_id=membership.user_id,
        email=req.email,
        role=req.role,
        ip_address=client_ip
    )
    return TenantMembershipRead.model_validate(new_mem)


@router.get("/{tenant_id}/members", response_model=List[TenantMembershipRead])
def list_tenant_members(
    tenant_id: uuid.UUID,
    membership: TenantMembership = Depends(PermissionChecker(Permission.VIEW_USERS)),
    session: Session = Depends(get_db_session)
):
    if membership.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to tenant environment."
        )

    stmt = select(TenantMembership).where(TenantMembership.tenant_id == tenant_id)
    memberships = session.execute(stmt).scalars().all()
    return [TenantMembershipRead.model_validate(m) for m in memberships]
