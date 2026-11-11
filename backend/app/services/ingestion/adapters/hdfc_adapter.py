import re
import uuid
from decimal import Decimal
from typing import List, Dict, Any, Tuple, Optional
from app.models.canonical import CanonicalBankTransaction
from app.models.ingestion import SourceType
from app.services.ingestion.adapters.base import (
    BaseAdapter,
    ParsedRowResult,
    RowQualityStatus,
    RowErrorDetail,
)
from app.services.ingestion.sanitizer import (
    parse_financial_decimal,
    parse_normalized_date,
    sanitize_csv_cell,
)


class HDFCBankAdapter(BaseAdapter):
    source_type = SourceType.HDFC

    # Regex patterns for Indian Bank UTR and nodal tokens
    UTR_PATTERNS = [
        re.compile(r"\b(HDFCR\d{12,20})\b", re.IGNORECASE),
        re.compile(r"\b(HDFCN\d{12,20})\b", re.IGNORECASE),
        re.compile(r"\b(CMS/RZP/NODAL/[A-Z0-9_-]+)\b", re.IGNORECASE),
        re.compile(r"\b(CMS/[A-Z0-9_-]+)\b", re.IGNORECASE),
        re.compile(r"\bUTR[:\s-]+([A-Z0-9]{12,22})\b", re.IGNORECASE),
        re.compile(r"\b(?:NEFT|RTGS|IMPS)[-/:]([A-Z0-9]{12,22})\b", re.IGNORECASE),
        re.compile(r"\b([A-Z]{4}R\d{10,18})\b", re.IGNORECASE),
    ]

    def _normalize_header(self, h: str) -> str:
        return h.strip().lower().replace(" ", "_").replace(".", "").replace("/", "_")

    def validate_headers(self, headers: List[str]) -> Tuple[bool, List[str]]:
        normalized = [self._normalize_header(h) for h in headers]
        missing = []

        # Check for date
        has_date = any(k in normalized for k in ["date", "txn_date", "transaction_date"])
        if not has_date:
            missing.append("Date/Txn Date")

        # Check for narration
        has_narration = any(k in normalized for k in ["narration", "description", "transaction_description"])
        if not has_narration:
            missing.append("Narration")

        # Check for deposit or credit
        has_amount = any(
            k in normalized
            for k in ["deposit_amt", "credit", "credit_amt", "deposit", "amount", "withdrawal_amt", "debit"]
        )
        if not has_amount:
            missing.append("Deposit/Credit Amount")

        return (len(missing) == 0, missing)

    def _extract_utr(self, narration: str, ref_no: Optional[str]) -> Optional[str]:
        # Check ref_no first
        if ref_no:
            cleaned_ref = ref_no.strip()
            if len(cleaned_ref) >= 8 and not cleaned_ref.startswith("000000"):
                return cleaned_ref

        # Inspect narration
        for pattern in self.UTR_PATTERNS:
            match = pattern.search(narration)
            if match:
                return match.group(1).strip()

        return None

    def parse_row(
        self,
        row_dict: Dict[str, Any],
        row_index: int,
        tenant_id: uuid.UUID,
        batch_id: uuid.UUID
    ) -> ParsedRowResult:
        errors: List[RowErrorDetail] = []
        raw_norm = {self._normalize_header(k): v for k, v in row_dict.items()}

        # 1. Date
        raw_date = raw_norm.get("date") or raw_norm.get("txn_date") or raw_norm.get("transaction_date")
        if not raw_date:
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="ERROR",
                    field_name="date",
                    raw_value=None,
                    error_code="MISSING_TXN_DATE",
                    message="Bank transaction missing date",
                    raw_record=row_dict,
                )
            )
            return ParsedRowResult(status=RowQualityStatus.INVALID, entity=None, errors=errors)

        try:
            txn_date = parse_normalized_date(raw_date)
        except Exception as e:
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="ERROR",
                    field_name="date",
                    raw_value=str(raw_date),
                    error_code="INVALID_DATE_FORMAT",
                    message=f"Failed to parse bank transaction date: {str(e)}",
                    raw_record=row_dict,
                )
            )
            return ParsedRowResult(status=RowQualityStatus.INVALID, entity=None, errors=errors)

        # Value date
        raw_val_date = raw_norm.get("value_dt") or raw_norm.get("value_date")
        value_date = None
        if raw_val_date:
            try:
                value_date = parse_normalized_date(raw_val_date)
            except:
                pass

        # 2. Narration
        raw_narration = (
            raw_norm.get("narration") or
            raw_norm.get("description") or
            raw_norm.get("transaction_description") or
            ""
        )
        narration_str = sanitize_csv_cell(str(raw_narration))
        if not narration_str:
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="WARNING",
                    field_name="narration",
                    raw_value=None,
                    error_code="EMPTY_NARRATION",
                    message="Bank statement line has empty narration description",
                    raw_record=row_dict,
                )
            )

        # 3. Reference No.
        raw_ref = (
            raw_norm.get("chq_ref_no") or
            raw_norm.get("chq_refno") or
            raw_norm.get("ref_no") or
            raw_norm.get("reference_no") or
            raw_norm.get("cheque_no")
        )
        bank_reference = sanitize_csv_cell(str(raw_ref)) if raw_ref else None

        # Extract UTR
        extracted_utr = self._extract_utr(narration_str, bank_reference)

        # 4. Deposit (Credit) and Withdrawal (Debit)
        raw_credit = (
            raw_norm.get("deposit_amt") or
            raw_norm.get("deposit") or
            raw_norm.get("credit") or
            raw_norm.get("credit_amt")
        )
        raw_debit = (
            raw_norm.get("withdrawal_amt") or
            raw_norm.get("withdrawal") or
            raw_norm.get("debit") or
            raw_norm.get("debit_amt")
        )

        credit_amount = Decimal("0.0000")
        debit_amount = Decimal("0.0000")

        if raw_credit:
            try:
                credit_amount = parse_financial_decimal(raw_credit)
            except Exception as e:
                errors.append(
                    RowErrorDetail(
                        row_index=row_index,
                        error_level="ERROR",
                        field_name="deposit_amt",
                        raw_value=str(raw_credit),
                        error_code="INVALID_CREDIT_AMOUNT",
                        message=f"Invalid deposit credit format: {str(e)}",
                        raw_record=row_dict,
                    )
                )

        if raw_debit:
            try:
                debit_amount = parse_financial_decimal(raw_debit)
            except Exception as e:
                errors.append(
                    RowErrorDetail(
                        row_index=row_index,
                        error_level="ERROR",
                        field_name="withdrawal_amt",
                        raw_value=str(raw_debit),
                        error_code="INVALID_DEBIT_AMOUNT",
                        message=f"Invalid withdrawal debit format: {str(e)}",
                        raw_record=row_dict,
                    )
                )

        if credit_amount == Decimal("0.0000") and debit_amount == Decimal("0.0000"):
            errors.append(
                RowErrorDetail(
                    row_index=row_index,
                    error_level="WARNING",
                    field_name="amount",
                    raw_value=None,
                    error_code="ZERO_AMOUNT_TRANSACTION",
                    message="Bank transaction has zero credit and zero debit",
                    raw_record=row_dict,
                )
            )

        # 5. Running Balance
        raw_balance = (
            raw_norm.get("closing_balance") or
            raw_norm.get("balance") or
            raw_norm.get("running_balance")
        )
        running_balance = None
        if raw_balance:
            try:
                running_balance = parse_financial_decimal(raw_balance)
            except:
                pass

        entity = CanonicalBankTransaction(
            tenant_id=tenant_id,
            batch_id=batch_id,
            source_row_index=row_index,
            bank_name="HDFC",
            bank_reference=bank_reference if bank_reference else None,
            extracted_utr=extracted_utr,
            raw_narration=narration_str,
            transaction_date=txn_date,
            value_date=value_date if value_date else txn_date,
            credit_amount=credit_amount,
            debit_amount=debit_amount,
            running_balance=running_balance,
            unallocated_balance=credit_amount,  # Credits start fully unallocated for reconciliation
            raw_source_data=row_dict,
        )

        status = RowQualityStatus.WARNING if len(errors) > 0 else RowQualityStatus.VALID
        return ParsedRowResult(status=status, entity=entity, errors=errors)
