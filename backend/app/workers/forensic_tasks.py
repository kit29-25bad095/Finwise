import uuid
import logging
from app.core.database import SessionLocal
from app.services.forensics.investigation_service import ForensicInvestigationService
from app.models.forensic import ForensicInvestigation, InvestigationStatus

logger = logging.getLogger(__name__)


def process_forensic_investigation_job(investigation_id_str: str) -> dict:
    """
    RQ background worker task for asynchronous forensic root cause investigation execution.
    """
    investigation_id = uuid.UUID(investigation_id_str)
    db = SessionLocal()
    try:
        inv = ForensicInvestigationService.execute_investigation(db, investigation_id)
        return {
            "investigation_id": str(inv.id),
            "tenant_id": str(inv.tenant_id),
            "exception_id": str(inv.exception_id),
            "status": inv.status,
            "conclusion": inv.conclusion,
            "confidence": inv.confidence,
            "model_provider": inv.model_provider,
            "model_name": inv.model_name,
        }
    except Exception as e:
        logger.exception(f"Unhandled error executing forensic investigation job {investigation_id}: {str(e)}")
        try:
            inv = db.get(ForensicInvestigation, investigation_id)
            if inv:
                inv.status = InvestigationStatus.FAILED.value
                inv.error_message = f"Worker runtime failure: {str(e)}"
                db.commit()
        except:
            pass
        raise
    finally:
        db.close()
