import csv
import io
import time
import hashlib
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.models.ingestion import IngestionBatch, SourceRowError, IngestionStatus, SourceType
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalBankTransaction,
)
from app.models.audit import AuditLog
from app.services.ingestion.adapters.base import BaseAdapter, RowQualityStatus
from app.services.ingestion.adapters.shopify_adapter import ShopifyAdapter
from app.services.ingestion.adapters.razorpay_adapter import RazorpayAdapter
from app.services.ingestion.adapters.hdfc_adapter import HDFCBankAdapter

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25MB


class IngestionService:
    @staticmethod
    def get_adapter(source_type: str) -> BaseAdapter:
        st = source_type.upper().strip()
        if st == SourceType.SHOPIFY:
            return ShopifyAdapter()
        elif st == SourceType.RAZORPAY:
            return RazorpayAdapter()
        elif st == SourceType.HDFC:
            return HDFCBankAdapter()
        else:
            raise ValueError(f"Unsupported data source type: '{source_type}'. Supported: SHOPIFY, RAZORPAY, HDFC.")

    @staticmethod
    def compute_sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def decode_csv_content(content: bytes) -> str:
        """
        Attempts decoding with encoding detection fallback.
        Handles UTF-8 with or without BOM, and Windows-1252 / Latin-1.
        """
        for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("Failed to decode CSV content with supported encodings (UTF-8, UTF-8-SIG, CP1252, Latin1).")

    @classmethod
    def register_upload(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        user_id: Optional[uuid.UUID],
        source_type: str,
        filename: str,
        file_bytes: bytes,
    ) -> Tuple[IngestionBatch, bool]:
        """
        Validates file size, MIME integrity, and checks for duplicate file uploads.
        Returns (IngestionBatch, is_duplicate).
        """
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"File size exceeds maximum allowable limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB.")

        if not filename.lower().endswith(".csv") and not filename.lower().endswith(".txt"):
            raise ValueError("Only CSV files are supported for ingestion.")

        file_hash = cls.compute_sha256(file_bytes)

        # Check for existing completed batch with identical hash for this tenant
        existing_batch = db.execute(
            select(IngestionBatch).where(
                and_(
                    IngestionBatch.tenant_id == tenant_id,
                    IngestionBatch.file_hash_sha256 == file_hash,
                    IngestionBatch.status.in_([
                        IngestionStatus.COMPLETED,
                        IngestionStatus.COMPLETED_WITH_WARNINGS,
                        IngestionStatus.PROCESSING
                    ])
                )
            )
        ).scalar_one_or_none()

        if existing_batch:
            # File already ingested
            return (existing_batch, True)

        batch = IngestionBatch(
            tenant_id=tenant_id,
            user_id=user_id,
            source_type=source_type.upper().strip(),
            filename=filename,
            file_hash_sha256=file_hash,
            file_size_bytes=len(file_bytes),
            status=IngestionStatus.UPLOADED,
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        return (batch, False)

    @classmethod
    def process_csv_batch(
        cls,
        db: Session,
        batch_id: uuid.UUID,
        file_bytes: bytes,
    ) -> IngestionBatch:
        """
        Core normalization pipeline: parses, validates, sanitizes, and normalizes
        records into canonical schema with complete provenance.
        """
        start_time = time.time()
        batch = db.get(IngestionBatch, batch_id)
        if not batch:
            raise ValueError(f"Batch '{batch_id}' not found.")

        if batch.status == IngestionStatus.CANCELLED:
            return batch

        batch.status = IngestionStatus.VALIDATING
        db.commit()

        adapter = cls.get_adapter(batch.source_type)

        try:
            text_content = cls.decode_csv_content(file_bytes)
        except Exception as e:
            batch.status = IngestionStatus.FAILED
            batch.error_message = f"File decoding error: {str(e)}"
            db.commit()
            return batch

        # Parse CSV
        reader = csv.DictReader(io.StringIO(text_content))
        if not reader.fieldnames:
            batch.status = IngestionStatus.FAILED
            batch.error_message = "CSV file contains no headers or is empty."
            db.commit()
            return batch

        # Validate headers
        is_valid_headers, missing_headers = adapter.validate_headers(list(reader.fieldnames))
        if not is_valid_headers:
            batch.status = IngestionStatus.FAILED
            batch.error_message = f"Missing required headers for {batch.source_type}: {', '.join(missing_headers)}"
            db.commit()
            return batch

        batch.status = IngestionStatus.PROCESSING
        db.commit()

        # Cache existing transaction identifiers to prevent duplicate canonical rows
        existing_order_refs = set()
        existing_payment_ids = set()
        existing_settlement_refs = set()

        if batch.source_type == SourceType.SHOPIFY:
            existing_order_refs = set(
                db.execute(select(CanonicalOrder.order_reference).where(CanonicalOrder.tenant_id == batch.tenant_id)).scalars().all()
            )
        elif batch.source_type == SourceType.RAZORPAY:
            existing_payment_ids = set(
                db.execute(select(CanonicalPayment.gateway_payment_id).where(CanonicalPayment.tenant_id == batch.tenant_id)).scalars().all()
            )
            existing_settlement_refs = set(
                db.execute(select(CanonicalSettlement.settlement_reference).where(CanonicalSettlement.tenant_id == batch.tenant_id)).scalars().all()
            )

        entities_to_add: List[Any] = []
        errors_to_add: List[SourceRowError] = []

        total_rows = 0
        valid_rows = 0
        invalid_rows = 0
        duplicate_rows = 0
        warning_rows = 0

        # Process each row
        for row_index, row in enumerate(reader, start=1):
            total_rows += 1
            result = adapter.parse_row(row, row_index, batch.tenant_id, batch.id)

            # Check for in-batch or database duplicate keys
            is_dup = False
            if result.entity:
                if isinstance(result.entity, CanonicalOrder):
                    if result.entity.order_reference in existing_order_refs:
                        is_dup = True
                    else:
                        existing_order_refs.add(result.entity.order_reference)

                elif isinstance(result.entity, CanonicalPayment):
                    if result.entity.gateway_payment_id in existing_payment_ids:
                        is_dup = True
                    else:
                        existing_payment_ids.add(result.entity.gateway_payment_id)

                elif isinstance(result.entity, CanonicalSettlement):
                    if result.entity.settlement_reference in existing_settlement_refs:
                        is_dup = True
                    else:
                        existing_settlement_refs.add(result.entity.settlement_reference)

            if is_dup:
                duplicate_rows += 1
                dup_err = SourceRowError(
                    tenant_id=batch.tenant_id,
                    batch_id=batch.id,
                    row_index=row_index,
                    error_level="DUPLICATE",
                    field_name="reference",
                    raw_value=getattr(result.entity, "order_reference", getattr(result.entity, "gateway_payment_id", "")),
                    error_code="DUPLICATE_TRANSACTION_KEY",
                    message="Transaction reference already exists in canonical ledger for this organization.",
                    raw_record=row,
                )
                errors_to_add.append(dup_err)
                continue

            if result.status == RowQualityStatus.INVALID:
                invalid_rows += 1
                for err in result.errors:
                    row_err = SourceRowError(
                        tenant_id=batch.tenant_id,
                        batch_id=batch.id,
                        row_index=err.row_index,
                        error_level=err.error_level,
                        field_name=err.field_name,
                        raw_value=err.raw_value,
                        error_code=err.error_code,
                        message=err.message,
                        raw_record=err.raw_record,
                    )
                    errors_to_add.append(row_err)
            else:
                valid_rows += 1
                if result.status == RowQualityStatus.WARNING:
                    warning_rows += 1
                    for err in result.errors:
                        row_err = SourceRowError(
                            tenant_id=batch.tenant_id,
                            batch_id=batch.id,
                            row_index=err.row_index,
                            error_level=err.error_level,
                            field_name=err.field_name,
                            raw_value=err.raw_value,
                            error_code=err.error_code,
                            message=err.message,
                            raw_record=err.raw_record,
                        )
                        errors_to_add.append(row_err)

                if result.entity:
                    entities_to_add.append(result.entity)

        # Bulk persist in one transaction
        if entities_to_add:
            db.add_all(entities_to_add)
        if errors_to_add:
            db.add_all(errors_to_add)

        # Update batch summary
        duration_ms = int((time.time() - start_time) * 1000)
        batch.total_rows = total_rows
        batch.valid_rows = valid_rows
        batch.invalid_rows = invalid_rows
        batch.duplicate_rows = duplicate_rows
        batch.warning_rows = warning_rows
        batch.processing_duration_ms = duration_ms
        batch.completed_at = datetime.now(timezone.utc)

        if valid_rows == 0 and invalid_rows > 0:
            batch.status = IngestionStatus.FAILED
            batch.error_message = f"All {invalid_rows} records in file contained fatal formatting errors."
        elif warning_rows > 0 or invalid_rows > 0 or duplicate_rows > 0:
            batch.status = IngestionStatus.COMPLETED_WITH_WARNINGS
        else:
            batch.status = IngestionStatus.COMPLETED

        # Audit Log
        audit = AuditLog(
            tenant_id=batch.tenant_id,
            user_id=batch.user_id,
            action="INGESTION_BATCH_PROCESSED",
            target_entity_type="ingestion_batches",
            target_entity_id=batch.id,
            user_rationale=f"Processed {batch.source_type} batch '{batch.filename}' ({valid_rows} valid, {invalid_rows} invalid, {duplicate_rows} duplicates in {duration_ms}ms).",
            new_state={
                "status": batch.status.value if hasattr(batch.status, "value") else str(batch.status),
                "total_rows": total_rows,
                "valid_rows": valid_rows,
                "invalid_rows": invalid_rows,
                "duplicate_rows": duplicate_rows,
            }
        )
        db.add(audit)

        db.commit()
        db.refresh(batch)
        return batch
