from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class IngestionBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: Optional[UUID] = None
    source_type: str
    filename: str
    file_hash_sha256: str
    file_size_bytes: int
    status: str
    error_message: Optional[str] = None
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    warning_rows: int
    processing_duration_ms: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class SourceRowErrorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    row_index: int
    error_level: str
    field_name: Optional[str] = None
    raw_value: Optional[str] = None
    error_code: str
    message: str
    raw_record: Optional[Dict[str, Any]] = None
    created_at: datetime


class ValidationReportResponse(BaseModel):
    batch: IngestionBatchResponse
    errors: List[SourceRowErrorResponse]
    error_count_by_code: Dict[str, int]
    warning_count_by_code: Dict[str, int]


class CanonicalOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    batch_id: UUID
    source_row_index: int
    order_reference: str
    order_number: Optional[str] = None
    customer_reference: Optional[str] = None
    gross_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    shipping_amount: Decimal
    currency: str
    fulfillment_status: Optional[str] = None
    financial_status: Optional[str] = None
    order_timestamp: datetime
    payment_gateway_names: Optional[str] = None
    created_at: datetime


class CanonicalPaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    batch_id: UUID
    source_row_index: int
    gateway_name: str
    gateway_payment_id: str
    gateway_order_id: Optional[str] = None
    order_reference: Optional[str] = None
    payment_method: Optional[str] = None
    card_network: Optional[str] = None
    card_type: Optional[str] = None
    captured_amount: Decimal
    reported_fee: Decimal
    reported_tax: Decimal
    currency: str
    status: str
    captured_at: datetime
    unallocated_balance: Decimal
    created_at: datetime


class CanonicalSettlementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    batch_id: UUID
    source_row_index: int
    gateway_name: str
    settlement_reference: str
    utr_number: Optional[str] = None
    gross_amount: Decimal
    total_fee: Decimal
    total_tax: Decimal
    total_refunds: Decimal
    total_adjustments: Decimal
    net_settlement_amount: Decimal
    unallocated_balance: Decimal
    status: str
    settled_at: datetime
    created_at: datetime


class CanonicalBankTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    batch_id: UUID
    source_row_index: int
    bank_name: str
    bank_reference: Optional[str] = None
    extracted_utr: Optional[str] = None
    raw_narration: str
    transaction_date: date
    value_date: Optional[date] = None
    credit_amount: Decimal
    debit_amount: Decimal
    running_balance: Optional[Decimal] = None
    unallocated_balance: Decimal
    created_at: datetime
