import uuid
import logging
from app.core.database import SessionLocal
from app.services.reconciliation.reconciliation_service import ReconciliationService
from app.models.reconciliation import ReconciliationRun, ReconciliationStatus

logger = logging.getLogger(__name__)


def process_reconciliation_job(run_id_str: str) -> dict:
    """
    RQ background worker task for asynchronous 3-way financial reconciliation execution.
    """
    run_id = uuid.UUID(run_id_str)
    db = SessionLocal()
    try:
        run = ReconciliationService.execute_run(db, run_id)
        return {
            "run_id": str(run.id),
            "run_number": run.run_number,
            "status": run.status,
            "matched_orders": run.matched_orders_count,
            "matched_payments": run.matched_payments_count,
            "matched_settlements": run.matched_settlements_count,
            "matched_bank_txs": run.matched_bank_txs_count,
            "total_discrepancy": str(run.total_discrepancy_amount),
            "duration_ms": run.duration_ms,
        }
    except Exception as e:
        logger.exception(f"Unhandled error executing reconciliation run {run_id}: {str(e)}")
        try:
            run = db.get(ReconciliationRun, run_id)
            if run:
                run.status = ReconciliationStatus.FAILED.value
                run.error_message = f"Worker runtime failure: {str(e)}"
                db.commit()
        except:
            pass
        raise
    finally:
        db.close()
