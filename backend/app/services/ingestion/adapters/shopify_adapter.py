import uuid
from decimal import Decimal
from typing import List, Dict, Any, Tuple
from app.models.canonical import CanonicalOrder
from app.models.ingestion import SourceType
from app.services.ingestion.adapters.base import (
    BaseAdapter,
    ParsedRowResult,
    RowQualityStatus,
    RowErrorDetail,
)
from app.services.ingestion.sanitizer import (
    parse_financial_decimal,
    parse_normalized_datetime,
    sanitize_csv_cell,
)


class ShopifyAdapter(BaseAdapter):
    source_type = SourceType.SHOPIFY

    REQUIRED_HEADERS = ["name", "total"]

    def _normalize_header(self, h: str) -> str:
        return h.strip().lower().replace(" ", "_").replace(".", "")

    def validate_headers(self, headers: List[str]) -> Tuple[bool, List[str]]:
        normalized = [self._normalize_header(h) for h in headers]
        missing = []

        # Check for order reference identifier
        has_ref = any(k in normalized for k in ["name", "order_id", "order_number", "order_name"])
        if not has_ref:
            missing.append("Name/Order ID")

        # Check for total amount
        has_total = any(k in normalized for k in ["total", "gross_amount", "amount", "total_amount"])
        if not has_total:
            missing.append("Total/Gross Amount")

        return (len(missing) == 0, missing)

    def parse_row(
        self,
        row_dict: Dict[str, Any],
        row_index: int,
        tenant_id: uuid.UUID,
        batch_id: uuid.UUID
    ) -> ParsedRowResult:
        errors: List[RowErrorDetail] = []
        raw_norm = {self._normalize_header(k): v for k, v in row_dict.items()}

        # 1. Order Reference
        order_ref = (
            raw_norm.get("name") or
            raw_norm.get("order_id") or
            raw_norm.get("order_name") or
            raw_norm.get("order_number")
        )
        if not order_ref:
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="ERROR",
                    field_name="name",
                    raw_value=None,
                    error_code="MISSING_ORDER_REFERENCE",
                    message="Shopify row missing mandatory order reference (Name/Order ID)",
                    raw_record=row_dict,
                )
            )
            return ParsedRowResult(status=RowQualityStatus.INVALID, entity=None, errors=errors)

        raw_ref_str = str(order_ref).strip()
        # Clean order number if contains '#' e.g. '#1001' -> '1001'
        raw_num_str = raw_ref_str.lstrip("#") if raw_ref_str.startswith("#") else raw_ref_str
        order_ref_str = sanitize_csv_cell(raw_ref_str)
        order_number_str = sanitize_csv_cell(raw_num_str)

        # 2. Total Gross Amount
        raw_total = (
            raw_norm.get("total") or
            raw_norm.get("gross_amount") or
            raw_norm.get("amount") or
            raw_norm.get("total_amount")
        )
        try:
            gross_amount = parse_financial_decimal(raw_total)
            if gross_amount < Decimal("0.0000"):
                errors.append(
                    RowErrorDetail(
                        row_index=row_index,
                        error_level="WARNING",
                        field_name="total",
                        raw_value=str(raw_total),
                        error_code="NEGATIVE_ORDER_TOTAL",
                        message=f"Negative order total encountered: {gross_amount}",
                        raw_record=row_dict,
                    )
                )
        except Exception as e:
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="ERROR",
                    field_name="total",
                    raw_value=str(raw_total),
                    error_code="INVALID_DECIMAL",
                    message=f"Invalid monetary format for total: {str(e)}",
                    raw_record=row_dict,
                )
            )
            return ParsedRowResult(status=RowQualityStatus.INVALID, entity=None, errors=errors)

        # 3. Timestamp
        raw_date = (
            raw_norm.get("created_at") or
            raw_norm.get("date") or
            raw_norm.get("order_date") or
            raw_norm.get("processed_at")
        )
        try:
            order_timestamp = parse_normalized_datetime(raw_date) if raw_date else parse_normalized_datetime("2026-01-01 00:00:00")
        except Exception as e:
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="ERROR",
                    field_name="created_at",
                    raw_value=str(raw_date),
                    error_code="INVALID_DATETIME",
                    message=f"Failed to parse order timestamp: {str(e)}",
                    raw_record=row_dict,
                )
            )
            return ParsedRowResult(status=RowQualityStatus.INVALID, entity=None, errors=errors)

        # 4. Optional monetary subtotals
        discount_amount = Decimal("0.0000")
        if "discount_amount" in raw_norm:
            try:
                discount_amount = parse_financial_decimal(raw_norm["discount_amount"])
            except:
                pass

        tax_amount = Decimal("0.0000")
        if "taxes" in raw_norm or "tax_amount" in raw_norm:
            try:
                tax_amount = parse_financial_decimal(raw_norm.get("taxes") or raw_norm.get("tax_amount"))
            except:
                pass

        shipping_amount = Decimal("0.0000")
        if "shipping" in raw_norm or "shipping_amount" in raw_norm:
            try:
                shipping_amount = parse_financial_decimal(raw_norm.get("shipping") or raw_norm.get("shipping_amount"))
            except:
                pass

        # 5. Metadata
        currency = str(raw_norm.get("currency") or "INR").strip().upper()
        if currency not in ("INR", "USD", "EUR", "GBP"):
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="WARNING",
                    field_name="currency",
                    raw_value=currency,
                    error_code="UNUSUAL_CURRENCY",
                    message=f"Unexpected currency '{currency}' detected",
                    raw_record=row_dict,
                )
            )

        fulfillment_status = sanitize_csv_cell(raw_norm.get("fulfillment_status"))
        financial_status = sanitize_csv_cell(raw_norm.get("financial_status") or "paid")
        customer_ref = sanitize_csv_cell(raw_norm.get("email") or raw_norm.get("customer_id") or raw_norm.get("customer_name"))
        payment_gateway = sanitize_csv_cell(raw_norm.get("payment_method") or raw_norm.get("payment_gateway_names") or raw_norm.get("gateway"))
        payment_references = sanitize_csv_cell(raw_norm.get("payment_reference") or raw_norm.get("transaction_id") or raw_norm.get("payment_id"))

        entity = CanonicalOrder(
            tenant_id=tenant_id,
            batch_id=batch_id,
            source_row_index=row_index,
            order_reference=order_ref_str,
            order_number=order_number_str,
            customer_reference=customer_ref if customer_ref else None,
            gross_amount=gross_amount,
            discount_amount=discount_amount,
            tax_amount=tax_amount,
            shipping_amount=shipping_amount,
            currency=currency,
            fulfillment_status=fulfillment_status if fulfillment_status else None,
            financial_status=financial_status if financial_status else None,
            order_timestamp=order_timestamp,
            payment_gateway_names=payment_gateway if payment_gateway else None,
            payment_references=payment_references if payment_references else None,
            raw_source_data=row_dict,
        )

        status = RowQualityStatus.WARNING if len(errors) > 0 else RowQualityStatus.VALID
        return ParsedRowResult(status=status, entity=entity, errors=errors)
