import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.audit import AuditLog
from app.core.rbac import Role
from app.schemas.tenant import TenantUpdate


class TenantService:
    @staticmethod
    def get_tenant_by_id(
        session: Session,
        tenant_id: uuid.UUID
    ) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active == True)
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_user_memberships(
        session: Session,
        user_id: uuid.UUID
    ) -> List[TenantMembership]:
        stmt = (
            select(TenantMembership)
            .join(Tenant)
            .where(
                TenantMembership.user_id == user_id,
                Tenant.is_active == True
            )
        )
        return list(session.execute(stmt).scalars().all())

    @staticmethod
    def add_member(
        session: Session,
        tenant_id: uuid.UUID,
        performed_by_id: uuid.UUID,
        email: str,
        role: Role,
        ip_address: Optional[str] = None
    ) -> TenantMembership:
        stmt_user = select(User).where(User.email == email.lower().strip())
        user = session.execute(stmt_user).scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with email '{email}' was not found. They must register first."
            )

        stmt_mem = select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user.id
        )
        existing = session.execute(stmt_mem).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already a member of this tenant."
            )

        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            role=role.value,
            is_default=False
        )
        session.add(membership)

        audit = AuditLog(
            tenant_id=tenant_id,
            user_id=performed_by_id,
            action="MEMBER_ADDED",
            target_entity_type="tenant_membership",
            target_entity_id=membership.id,
            new_state={"user_email": user.email, "role": role.value},
            user_rationale="Added team member to tenant",
            ip_address=ip_address
        )
        session.add(audit)
        session.commit()
        session.refresh(membership)
        return membership

    @staticmethod
    def update_tenant(
        session: Session,
        tenant_id: uuid.UUID,
        performed_by_id: uuid.UUID,
        update_data: TenantUpdate,
        ip_address: Optional[str] = None
    ) -> Tenant:
        tenant = TenantService.get_tenant_by_id(session, tenant_id)
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found."
            )

        prev_state = {
            "name": tenant.name,
            "settlement_cutoff_time": tenant.settlement_cutoff_time,
            "fee_overcharge_tolerance": str(tenant.fee_overcharge_tolerance),
            "max_knapsack_bound": tenant.max_knapsack_bound
        }

        if update_data.name is not None:
            tenant.name = update_data.name
        if update_data.settlement_cutoff_time is not None:
            tenant.settlement_cutoff_time = update_data.settlement_cutoff_time
        if update_data.fee_overcharge_tolerance is not None:
            tenant.fee_overcharge_tolerance = update_data.fee_overcharge_tolerance
        if update_data.max_knapsack_bound is not None:
            tenant.max_knapsack_bound = update_data.max_knapsack_bound

        new_state = {
            "name": tenant.name,
            "settlement_cutoff_time": tenant.settlement_cutoff_time,
            "fee_overcharge_tolerance": str(tenant.fee_overcharge_tolerance),
            "max_knapsack_bound": tenant.max_knapsack_bound
        }

        audit = AuditLog(
            tenant_id=tenant_id,
            user_id=performed_by_id,
            action="TENANT_SETTINGS_UPDATED",
            target_entity_type="tenant",
            target_entity_id=tenant.id,
            previous_state=prev_state,
            new_state=new_state,
            user_rationale="Updated tenant configuration",
            ip_address=ip_address
        )
        session.add(audit)
        session.commit()
        session.refresh(tenant)
        return tenant
