import uuid
from decimal import Decimal
from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    DateTime,
    Date,
    ForeignKey,
    Text,
    JSON,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class CanonicalOrder(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Normalized Order from Shopify or Order Management Systems.
    """
    __tablename__ = "canonical_orders"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    source_row_index = Column(Integer, nullable=False)

    order_reference = Column(String(100), nullable=False)  # e.g. "ORD-98421" or "#1001"
    order_number = Column(String(100), nullable=True)     # e.g. "1001"
    customer_reference = Column(String(255), nullable=True)

    gross_amount = Column(Numeric(18, 4), nullable=False)
    discount_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    tax_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    shipping_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    currency = Column(String(3), nullable=False, default="INR")

    fulfillment_status = Column(String(50), nullable=True)
    financial_status = Column(String(50), nullable=True)  # paid, pending, refunded, partially_refunded
    order_timestamp = Column(DateTime(timezone=True), nullable=False)

    payment_gateway_names = Column(String(255), nullable=True)
    payment_references = Column(Text, nullable=True)  # JSON or comma-separated transaction tokens

    raw_source_data = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_orders_tenant_ref", "tenant_id", "order_reference"),
        Index("ix_orders_tenant_date", "tenant_id", "order_timestamp"),
        UniqueConstraint("tenant_id", "order_reference", name="uq_tenant_order_reference"),
    )


class CanonicalPayment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Normalized Payment Capture event from Gateway (Razorpay).
    """
    __tablename__ = "canonical_payments"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    source_row_index = Column(Integer, nullable=False)

    gateway_name = Column(String(50), nullable=False, default="RAZORPAY")
    gateway_payment_id = Column(String(100), nullable=False)  # e.g. "pay_Oz91M202Kaa"
    gateway_order_id = Column(String(100), nullable=True)    # e.g. "order_Oz91M202Kaa" or OMS order reference
    order_reference = Column(String(100), nullable=True)      # Correlated order reference

    payment_method = Column(String(50), nullable=True)        # UPI, card, netbanking, wallet
    card_network = Column(String(50), nullable=True)          # Visa, Mastercard, RuPay
    card_type = Column(String(50), nullable=True)             # consumer, corporate, commercial

    captured_amount = Column(Numeric(18, 4), nullable=False)
    reported_fee = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    reported_tax = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    currency = Column(String(3), nullable=False, default="INR")

    status = Column(String(50), nullable=False, default="captured")  # captured, refunded, failed
    captured_at = Column(DateTime(timezone=True), nullable=False)

    unallocated_balance = Column(Numeric(18, 4), nullable=False)
    raw_source_data = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_payments_tenant_payid", "tenant_id", "gateway_payment_id"),
        Index("ix_payments_tenant_captured_at", "tenant_id", "captured_at"),
        UniqueConstraint("tenant_id", "gateway_payment_id", name="uq_tenant_gateway_payment_id"),
    )


class CanonicalSettlement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Normalized Settlement Batch from Payment Gateway (Razorpay).
    """
    __tablename__ = "canonical_settlements"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    source_row_index = Column(Integer, nullable=False)

    gateway_name = Column(String(50), nullable=False, default="RAZORPAY")
    settlement_reference = Column(String(100), nullable=False)  # e.g. "SETL-20261110-09"
    utr_number = Column(String(100), nullable=True)            # e.g. "HDFCR5202611110098"

    gross_amount = Column(Numeric(18, 4), nullable=False)
    total_fee = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    total_tax = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    total_refunds = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    total_adjustments = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    net_settlement_amount = Column(Numeric(18, 4), nullable=False)
    unallocated_balance = Column(Numeric(18, 4), nullable=False)

    status = Column(String(50), nullable=False, default="settled")
    settled_at = Column(DateTime(timezone=True), nullable=False)
    raw_source_data = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_settle_tenant_ref", "tenant_id", "settlement_reference"),
        Index("ix_settle_tenant_utr", "tenant_id", "utr_number"),
        UniqueConstraint("tenant_id", "settlement_reference", name="uq_tenant_settlement_reference"),
    )


class CanonicalRefund(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Normalized Refund Event from Gateway or OMS.
    """
    __tablename__ = "canonical_refunds"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    source_row_index = Column(Integer, nullable=False)

    gateway_refund_id = Column(String(100), nullable=False)
    gateway_payment_id = Column(String(100), nullable=True)
    order_reference = Column(String(100), nullable=True)

    refund_amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    status = Column(String(50), nullable=False, default="processed")

    initiated_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    raw_source_data = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_refunds_tenant_refid", "tenant_id", "gateway_refund_id"),
        # Relaxed in Phase 4: UniqueConstraint prevented importing lifecycle retry attempts and detecting duplicate gateway refunds.
    )


class CanonicalBankTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Normalized Bank Statement line-item credit or debit (HDFC Bank Current Account).
    """
    __tablename__ = "canonical_bank_transactions"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    source_row_index = Column(Integer, nullable=False)

    bank_name = Column(String(50), nullable=False, default="HDFC")
    bank_reference = Column(String(100), nullable=True)    # Chq/Ref No.
    extracted_utr = Column(String(100), nullable=True)     # Extracted RTGS/NEFT/IMPS token
    raw_narration = Column(Text, nullable=False)

    transaction_date = Column(Date, nullable=False)
    value_date = Column(Date, nullable=True)

    credit_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    debit_amount = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    running_balance = Column(Numeric(18, 4), nullable=True)
    unallocated_balance = Column(Numeric(18, 4), nullable=False)

    raw_source_data = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_bank_tenant_date", "tenant_id", "transaction_date"),
        Index("ix_bank_tenant_utr", "tenant_id", "extracted_utr"),
        Index("ix_bank_tenant_ref", "tenant_id", "bank_reference"),
    )
