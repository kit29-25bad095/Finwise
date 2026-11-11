import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.core.rbac import Role


class TenantBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100)
    default_currency: str = Field("INR", min_length=3, max_length=3)
    settlement_cutoff_time: str = Field("23:00", pattern=r"^\d{2}:\d{2}$")
    fee_overcharge_tolerance: Decimal = Field(Decimal("0.0500"), ge=0, le=1)
    max_knapsack_bound: int = Field(5, ge=1, le=10)


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    settlement_cutoff_time: Optional[str] = None
    fee_overcharge_tolerance: Optional[Decimal] = None
    max_knapsack_bound: Optional[int] = None
    is_active: Optional[bool] = None


class TenantRead(TenantBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TenantMembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    is_default: bool
    created_at: datetime
    tenant: Optional[TenantRead] = None


class AddMemberRequest(BaseModel):
    email: str
    role: Role = Role.FINANCE_MANAGER
