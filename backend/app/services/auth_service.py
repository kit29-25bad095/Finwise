import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.rbac import Role
from app.models.user import User
from app.models.tenant import Tenant, TenantMembership
from app.models.audit import AuditLog
from app.schemas.auth import RegisterRequest, TokenResponse
from app.schemas.user import UserRead
from app.schemas.tenant import TenantMembershipRead


class AuthService:
    @staticmethod
    def authenticate_user(
        session: Session,
        email: str,
        password: str
    ) -> Optional[User]:
        stmt = select(User).where(User.email == email.lower().strip())
        user = session.execute(stmt).scalar_one_or_none()
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    @staticmethod
    def register_user_with_tenant(
        session: Session,
        req: RegisterRequest,
        ip_address: Optional[str] = None
    ) -> TokenResponse:
        # Check if email exists
        stmt_user = select(User).where(User.email == req.email.lower().strip())
        existing_user = session.execute(stmt_user).scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email address already exists."
            )

        # Check if tenant slug exists
        clean_slug = req.tenant_slug.lower().strip()
        stmt_tenant = select(Tenant).where(Tenant.slug == clean_slug)
        existing_tenant = session.execute(stmt_tenant).scalar_one_or_none()
        if existing_tenant:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A business with this identifier already exists. Please choose another slug."
            )

        # Create Tenant
        tenant = Tenant(
            name=req.tenant_name.strip(),
            slug=clean_slug
        )
        session.add(tenant)
        session.flush()

        # Create User
        user = User(
            email=req.email.lower().strip(),
            hashed_password=get_password_hash(req.password),
            full_name=req.full_name.strip()
        )
        session.add(user)
        session.flush()

        # Create Admin Membership
        membership = TenantMembership(
            tenant_id=tenant.id,
            user_id=user.id,
            role=Role.ADMIN.value,
            is_default=True
        )
        session.add(membership)

        # Record Initial Audit Log
        audit = AuditLog(
            tenant_id=tenant.id,
            user_id=user.id,
            action="TENANT_REGISTERED",
            target_entity_type="tenant",
            target_entity_id=tenant.id,
            new_state={"tenant_name": tenant.name, "owner_email": user.email},
            user_rationale="Initial account and tenant registration",
            ip_address=ip_address
        )
        session.add(audit)
        session.commit()
        session.refresh(user)

        token = create_access_token(
            subject=user.id,
            tenant_id=tenant.id,
            role=Role.ADMIN.value
        )

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            user=UserRead.model_validate(user),
            active_tenant_id=tenant.id,
            active_role=Role.ADMIN.value,
            memberships=[TenantMembershipRead.model_validate(membership)]
        )

    @staticmethod
    def create_token_for_user(
        user: User,
        tenant_id: Optional[uuid.UUID] = None,
        role: Optional[str] = None
    ) -> str:
        return create_access_token(
            subject=user.id,
            tenant_id=tenant_id,
            role=role
        )
