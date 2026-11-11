import uuid
from typing import List, Optional
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import decode_access_token
from app.core.rbac import Role, Permission, has_permission
from app.models.user import User
from app.models.tenant import Tenant, TenantMembership

security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    session: Session = Depends(get_db_session)
) -> User:
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    payload = decode_access_token(auth.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token subject identifier.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    stmt = select(User).where(User.id == user_id, User.is_active == True)
    user = session.execute(stmt).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account does not exist or has been deactivated.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return user


def get_current_tenant_membership(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")
) -> TenantMembership:
    target_tenant_id: Optional[uuid.UUID] = None

    if auth and auth.credentials:
        payload = decode_access_token(auth.credentials)
        if payload and payload.get("tenant_id"):
            try:
                target_tenant_id = uuid.UUID(payload["tenant_id"])
            except ValueError:
                pass

    if x_tenant_id:
        try:
            target_tenant_id = uuid.UUID(x_tenant_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Tenant-ID header format. Must be a valid UUID."
            )

    stmt = (
        select(TenantMembership)
        .join(Tenant)
        .where(
            TenantMembership.user_id == current_user.id,
            Tenant.is_active == True
        )
    )
    if target_tenant_id:
        stmt = stmt.where(TenantMembership.tenant_id == target_tenant_id)

    memberships = session.execute(stmt).scalars().all()
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have authorized access to the requested tenant environment."
        )

    return memberships[0]


class RoleChecker:
    def __init__(self, allowed_roles: List[Role]):
        self.allowed_roles = [r.value for r in allowed_roles]

    def __call__(
        self,
        membership: TenantMembership = Depends(get_current_tenant_membership)
    ) -> TenantMembership:
        if membership.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of the following roles: {', '.join(self.allowed_roles)}. Current role: '{membership.role}'."
            )
        return membership


class PermissionChecker:
    def __init__(self, required_permission: Permission):
        self.required_permission = required_permission

    def __call__(
        self,
        membership: TenantMembership = Depends(get_current_tenant_membership)
    ) -> TenantMembership:
        role_enum = Role(membership.role)
        if not has_permission(role_enum, self.required_permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: '{self.required_permission.value}' is required for this action."
            )
        return membership
