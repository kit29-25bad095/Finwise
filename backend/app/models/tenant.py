import uuid
from decimal import Decimal
from typing import List, TYPE_CHECKING
from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.rbac import Role
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, ImmutabilityViolationError

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.audit import AuditLog


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    default_currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    settlement_cutoff_time: Mapped[str] = mapped_column(String(5), default="23:00", nullable=False)
    fee_overcharge_tolerance: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        default=Decimal("0.0500"),
        nullable=False
    )
    max_knapsack_bound: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    memberships: Mapped[List["TenantMembership"]] = relationship(
        "TenantMembership",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="tenant",
        lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Tenant {self.name} ({self.slug})>"


class TenantMembership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user_membership"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    role: Mapped[str] = mapped_column(String(50), default=Role.FINANCE_MANAGER.value, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="memberships")
    user: Mapped["User"] = relationship("User", back_populates="memberships")

    def __repr__(self) -> str:
        return f"<TenantMembership user={self.user_id} tenant={self.tenant_id} role={self.role}>"


def _prevent_tenant_delete(mapper, connection, target):
    raise ImmutabilityViolationError(
        f"Hard deletion of Tenant '{target.id}' ({target.slug}) is strictly prohibited to preserve historical financial and audit records. Use soft deactivation (is_active=False) instead."
    )


event.listen(Tenant, "before_delete", _prevent_tenant_delete)
