import uuid
from decimal import Decimal
from typing import List, Dict, Any, Tuple
from app.models.canonical import CanonicalPayment, CanonicalSettlement, CanonicalRefund
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


class RazorpayAdapter(BaseAdapter):
    source_type = SourceType.RAZORPAY

    def _normalize_header(self, h: str) -> str:
        return h.strip().lower().replace(" ", "_").replace(".", "")

    def validate_headers(self, headers: List[str]) -> Tuple[bool, List[str]]:
        normalized = [self._normalize_header(h) for h in headers]
        missing = []

        # Check for payment ID or settlement ID or entity identifier
        has_id = any(k in normalized for k in ["payment_id", "entity_id", "id", "settlement_id", "txn_id"])
        if not has_id:
            missing.append("payment_id/settlement_id")

        # Check for amount
        has_amount = any(k in normalized for k in ["amount", "gross_amount", "captured_amount", "credit"])
        if not has_amount:
            missing.append("amount")

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

        # Identify entity type: Is this a settlement batch summary or payment capture?
        payment_id = (
            raw_norm.get("payment_id") or
            raw_norm.get("entity_id") or
            raw_norm.get("id") or
            raw_norm.get("txn_id")
        )
        settlement_id = (
            raw_norm.get("settlement_id") or
            raw_norm.get("settlement_batch_id") or
            raw_norm.get("batch_id")
        )
        utr_number = (
            raw_norm.get("utr") or
            raw_norm.get("bank_utr") or
            raw_norm.get("utr_number") or
            raw_norm.get("rrn")
        )

        if not payment_id and not settlement_id:
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="ERROR",
                    field_name="payment_id",
                    raw_value=None,
                    error_code="MISSING_GATEWAY_IDENTIFIER",
                    message="Razorpay row missing both payment_id and settlement_id",
                    raw_record=row_dict,
                )
            )
            return ParsedRowResult(status=RowQualityStatus.INVALID, entity=None, errors=errors)

        # 1. Amount Parsing
        raw_amount = (
            raw_norm.get("amount") or
            raw_norm.get("captured_amount") or
            raw_norm.get("gross_amount") or
            raw_norm.get("credit")
        )
        try:
            captured_amount = parse_financial_decimal(raw_amount)
        except Exception as e:
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="ERROR",
                    field_name="amount",
                    raw_value=str(raw_amount),
                    error_code="INVALID_DECIMAL",
                    message=f"Invalid monetary format for amount: {str(e)}",
                    raw_record=row_dict,
                )
            )
            return ParsedRowResult(status=RowQualityStatus.INVALID, entity=None, errors=errors)

        # 2. Fee and Tax
        reported_fee = Decimal("0.0000")
        if "fee" in raw_norm:
            try:
                reported_fee = parse_financial_decimal(raw_norm["fee"])
            except:
                pass

        reported_tax = Decimal("0.0000")
        if "tax" in raw_norm:
            try:
                reported_tax = parse_financial_decimal(raw_norm["tax"])
            except:
                pass

        # 3. Timestamps
        raw_date = (
            raw_norm.get("created_at") or
            raw_norm.get("captured_at") or
            raw_norm.get("settled_at") or
            raw_norm.get("date")
        )
        try:
            timestamp = parse_normalized_datetime(raw_date) if raw_date else parse_normalized_datetime("2026-01-01 00:00:00")
        except Exception as e:
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="ERROR",
                    field_name="created_at",
                    raw_value=str(raw_date),
                    error_code="INVALID_DATETIME",
                    message=f"Failed to parse Razorpay timestamp: {str(e)}",
                    raw_record=row_dict,
                )
            )
            return ParsedRowResult(status=RowQualityStatus.INVALID, entity=None, errors=errors)

        # 4. If row is exclusively a Settlement Batch
        is_pure_settlement = settlement_id and not payment_id
        if is_pure_settlement:
            settlement_ref_str = str(settlement_id).strip()
            utr_str = sanitize_csv_cell(utr_number) if utr_number else None
            net_amount = captured_amount - (reported_fee + reported_tax)

            settlement_entity = CanonicalSettlement(
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_row_index=row_index,
                gateway_name="RAZORPAY",
                settlement_reference=settlement_ref_str,
                utr_number=utr_str if utr_str else None,
                gross_amount=captured_amount,
                total_fee=reported_fee,
                total_tax=reported_tax,
                total_refunds=Decimal("0.0000"),
                total_adjustments=Decimal("0.0000"),
                net_settlement_amount=net_amount,
                unallocated_balance=net_amount,
                status="settled",
                settled_at=timestamp,
                raw_source_data=row_dict,
            )
            return ParsedRowResult(status=RowQualityStatus.VALID, entity=settlement_entity, errors=[])

        # Otherwise, parse as Payment Capture
        payment_id_str = str(payment_id).strip()
        gateway_order_id = sanitize_csv_cell(raw_norm.get("order_id"))
        payment_method = sanitize_csv_cell(raw_norm.get("method") or raw_norm.get("payment_method"))
        card_network = sanitize_csv_cell(raw_norm.get("card_network") or raw_norm.get("network"))
        card_type = sanitize_csv_cell(raw_norm.get("card_type") or raw_norm.get("type"))
        status_val = str(raw_norm.get("status") or "captured").strip().lower()

        payment_entity = CanonicalPayment(
            tenant_id=tenant_id,
            batch_id=batch_id,
            source_row_index=row_index,
            gateway_name="RAZORPAY",
            gateway_payment_id=payment_id_str,
            gateway_order_id=gateway_order_id if gateway_order_id else None,
            order_reference=gateway_order_id if gateway_order_id else None,
            payment_method=payment_method if payment_method else None,
            card_network=card_network if card_network else None,
            card_type=card_type if card_type else None,
            captured_amount=captured_amount,
            reported_fee=reported_fee,
            reported_tax=reported_tax,
            currency="INR",
            status=status_val,
            captured_at=timestamp,
            unallocated_balance=captured_amount,
            raw_source_data=row_dict,
        )

        status = RowQualityStatus.WARNING if len(errors) > 0 else RowQualityStatus.VALID
        return ParsedRowResult(status=status, entity=payment_entity, errors=errors)
