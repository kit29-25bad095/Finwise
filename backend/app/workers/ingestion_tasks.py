import uuid
import logging
from app.core.database import SessionLocal
from app.services.ingestion.ingestion_service import IngestionService
from app.models.ingestion import IngestionBatch, IngestionStatus

logger = logging.getLogger(__name__)


def process_ingestion_job(batch_id_str: str, file_bytes: bytes) -> dict:
    """
    RQ background worker task for asynchronous CSV processing.
    """
    batch_id = uuid.UUID(batch_id_str)
    db = SessionLocal()
    try:
        batch = IngestionService.process_csv_batch(db, batch_id, file_bytes)
        return {
            "batch_id": str(batch.id),
            "status": batch.status,
            "total_rows": batch.total_rows,
            "valid_rows": batch.valid_rows,
            "invalid_rows": batch.invalid_rows,
            "duplicate_rows": batch.duplicate_rows,
            "duration_ms": batch.processing_duration_ms,
        }
    except Exception as e:
        logger.exception(f"Unhandled error processing ingestion batch {batch_id}: {str(e)}")
        try:
            batch = db.get(IngestionBatch, batch_id)
            if batch:
                batch.status = IngestionStatus.FAILED
                batch.error_message = f"Worker runtime failure: {str(e)}"
                db.commit()
        except:
            pass
        raise
    finally:
        db.close()
