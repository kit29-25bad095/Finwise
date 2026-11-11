import uuid
from typing import Optional, List
from pydantic import BaseModel, EmailStr
from app.schemas.user import UserRead
from app.schemas.tenant import TenantMembershipRead


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_id: Optional[uuid.UUID] = None


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    tenant_name: str
    tenant_slug: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
    active_tenant_id: Optional[uuid.UUID] = None
    active_role: Optional[str] = None
    memberships: List[TenantMembershipRead] = []


class TokenPayload(BaseModel):
    sub: str
    tenant_id: Optional[str] = None
    role: Optional[str] = None
    exp: int
