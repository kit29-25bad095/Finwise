import uuid
import logging
from app.core.database import SessionLocal
from app.services.leakage.detection_engine import DetectionEngine
from app.models.leakage import LeakageDetectionRun, DetectionRunStatus

logger = logging.getLogger(__name__)


def process_leakage_detection_job(run_id_str: str) -> dict:
    """
    RQ background worker task for asynchronous leakage detection execution.
    """
    run_id = uuid.UUID(run_id_str)
    db = SessionLocal()
    try:
        run = DetectionEngine.execute_run(db, run_id)
        return {
            "run_id": str(run.id),
            "run_number": run.run_number,
            "status": run.status,
            "exceptions_count": run.exceptions_count,
            "total_leakage": str(run.total_leakage_amount),
            "total_potential_recovery": str(run.total_potential_recovery),
            "duration_ms": run.duration_ms,
        }
    except Exception as e:
        logger.exception(f"Unhandled error executing leakage detection run {run_id}: {str(e)}")
        try:
            run = db.get(LeakageDetectionRun, run_id)
            if run:
                run.status = DetectionRunStatus.FAILED.value
                run.error_message = f"Worker runtime failure: {str(e)}"
                db.commit()
        except:
            pass
        raise
    finally:
        db.close()
