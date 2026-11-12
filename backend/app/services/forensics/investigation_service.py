import uuid
import asyncio
import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, desc

from app.models.forensic import (
    ForensicInvestigation,
    InvestigationStatus,
    InvestigationConclusion,
    InvestigationConfidence,
)
from app.models.leakage import LeakageException
from app.services.forensics.exceptions import (
    ResourceNotFoundError,
    EvidenceIntegrityError,
    LLMProviderError,
    InvalidInvestigationStateError,
)
from app.services.forensics.forensic_reader import LeakageForensicReader
from app.services.forensics.evidence_bundle_builder import EvidenceBundleBuilder
from app.services.forensics.prompt_builder import ForensicPromptBuilder
from app.services.forensics.confidence_evaluator import ConfidenceEvaluator
from app.services.forensics.llm_adapter import BaseLLMAdapter, get_llm_adapter

logger = logging.getLogger(__name__)


class ForensicInvestigationService:
    """
    Core orchestrator for Phase 5 AI Forensic Investigations.
    Coordinates evidence retrieval, canonical bundle construction, secure LLM prompt dispatch,
    deterministic confidence evaluation, and immutable audit persistence.
    """

    @classmethod
    def create_investigation(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        exception_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        idempotency_key: Optional[str] = None,
        force_refresh: bool = False,
    ) -> ForensicInvestigation:
        """
        Creates or retrieves an investigation record with idempotency and snapshot caching.
        """
        # 1. Idempotency Check
        if idempotency_key:
            stmt_idem = select(ForensicInvestigation).where(
                and_(
                    ForensicInvestigation.tenant_id == tenant_id,
                    ForensicInvestigation.idempotency_key == idempotency_key
                )
            )
            existing = db.execute(stmt_idem).scalar_one_or_none()
            if existing:
                logger.info(f"Returning idempotent investigation {existing.id} for key '{idempotency_key}'.")
                return existing

        # 2. Fetch Exception with strict tenancy check
        exception = LeakageForensicReader.get_exception(db, tenant_id, exception_id)

        # 3. Determine detection run lineage
        target_run_id = exception.latest_detection_run_id or exception.detection_run_id

        # 4. Snapshot Reuse Check (unless forced)
        if not force_refresh:
            stmt_recent = (
                select(ForensicInvestigation)
                .where(
                    and_(
                        ForensicInvestigation.tenant_id == tenant_id,
                        ForensicInvestigation.exception_id == exception_id,
                        ForensicInvestigation.detection_run_id == target_run_id,
                        ForensicInvestigation.status.in_([
                            InvestigationStatus.COMPLETED.value,
                            InvestigationStatus.IN_PROGRESS.value,
                            InvestigationStatus.PENDING.value
                        ])
                    )
                )
                .order_by(desc(ForensicInvestigation.created_at))
            )
            existing_for_run = db.execute(stmt_recent).scalars().first()
            if existing_for_run:
                logger.info(
                    f"Reusing existing investigation {existing_for_run.id} for exception {exception_id} "
                    f"and detection run {target_run_id}."
                )
                return existing_for_run

        # 5. Fetch point-in-time run snapshot and evidence items
        snapshot = LeakageForensicReader.get_run_snapshot(db, tenant_id, exception_id, target_run_id)
        evidence_items = LeakageForensicReader.get_evidence_for_run(db, tenant_id, exception_id, target_run_id)
        reviews = LeakageForensicReader.get_reviewer_history(db, tenant_id, exception_id)
        latest_notes = reviews[0].notes if reviews and reviews[0].notes else exception.resolution_notes

        # 6. Build Deterministic Canonical Evidence Bundle
        bundle_snapshot, bundle_fingerprint, all_verified = EvidenceBundleBuilder.build_bundle(
            exception=exception,
            run_id=target_run_id,
            snapshot=snapshot,
            evidence_items=evidence_items,
            reviewer_notes=latest_notes
        )

        # 7. Create Investigation in PENDING state
        investigation = ForensicInvestigation(
            tenant_id=tenant_id,
            exception_id=exception_id,
            detection_run_id=target_run_id,
            idempotency_key=idempotency_key,
            status=InvestigationStatus.PENDING.value,
            conclusion=InvestigationConclusion.INCONCLUSIVE.value,
            confidence=InvestigationConfidence.LOW.value,
            summary="Investigation queued for execution.",
            evidence_bundle_fingerprint=bundle_fingerprint,
            evidence_bundle_snapshot=bundle_snapshot,
            investigation_result=None,
            model_provider=get_llm_adapter().provider_name,
            model_name=get_llm_adapter().model_name,
            prompt_version=ForensicPromptBuilder.PROMPT_VERSION,
            schema_version=ForensicPromptBuilder.SCHEMA_VERSION,
            created_by_user_id=user_id,
        )

        db.add(investigation)
        db.commit()
        db.refresh(investigation)
        return investigation

    @classmethod
    async def execute_investigation_async(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        adapter: Optional[BaseLLMAdapter] = None
    ) -> ForensicInvestigation:
        """
        Asynchronously executes the investigation: validates evidence, dispatches to LLM,
        and deterministically bounds confidence.
        """
        inv = db.get(ForensicInvestigation, investigation_id)
        if not inv:
            raise ResourceNotFoundError(f"Forensic investigation {investigation_id} not found.")

        bundle = inv.evidence_bundle_snapshot or {}
        all_verified = bundle.get("all_evidence_verified", False)
        evidence_items = bundle.get("evidence_items", [])

        inv.status = InvestigationStatus.IN_PROGRESS.value
        db.commit()

        # Step 1: Pre-flight Evidence Integrity Guard
        if not all_verified:
            inv.status = InvestigationStatus.BLOCKED.value
            inv.conclusion = InvestigationConclusion.INCONCLUSIVE.value
            inv.confidence = InvestigationConfidence.LOW.value
            inv.summary = (
                "Forensic investigation blocked: One or more evidence records failed cryptographic "
                "integrity verification or tenancy bounds."
            )
            inv.error_message = "Cryptographic evidence integrity check failed."
            db.commit()
            db.refresh(inv)
            return inv

        if not evidence_items:
            inv.status = InvestigationStatus.COMPLETED.value
            inv.conclusion = InvestigationConclusion.INCONCLUSIVE.value
            inv.confidence = InvestigationConfidence.LOW.value
            inv.summary = "No evidence records were found to evaluate for this exception and run."
            db.commit()
            db.refresh(inv)
            return inv

        # Step 2: Build Secure Prompts
        system_prompt = ForensicPromptBuilder.get_system_prompt()
        user_prompt = ForensicPromptBuilder.build_user_prompt(bundle)

        # Step 3: Dispatch to LLM
        active_adapter = adapter or get_llm_adapter()
        try:
            raw_result = await active_adapter.generate_investigation(
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )

            # Step 4: Deterministic Confidence & Conclusion Evaluation
            result_contract, conclusion, confidence = ConfidenceEvaluator.evaluate(
                raw_result=raw_result,
                evidence_bundle=bundle
            )

            inv.status = InvestigationStatus.COMPLETED.value
            inv.conclusion = conclusion.value
            inv.confidence = confidence.value
            inv.summary = result_contract.summary
            inv.investigation_result = result_contract.model_dump()
            inv.model_provider = active_adapter.provider_name
            inv.model_name = active_adapter.model_name
            inv.error_message = None

        except LLMProviderError as e:
            logger.error(f"LLM Provider failure for investigation {investigation_id}: {str(e)}")
            inv.status = InvestigationStatus.FAILED.value
            inv.conclusion = InvestigationConclusion.INCONCLUSIVE.value
            inv.confidence = InvestigationConfidence.LOW.value
            inv.error_message = f"AI Provider failure: {str(e)}"
        except Exception as e:
            logger.exception(f"Unexpected error executing investigation {investigation_id}: {str(e)}")
            inv.status = InvestigationStatus.FAILED.value
            inv.conclusion = InvestigationConclusion.INCONCLUSIVE.value
            inv.confidence = InvestigationConfidence.LOW.value
            inv.error_message = f"Runtime execution error: {str(e)}"

        db.commit()
        db.refresh(inv)
        return inv

    @classmethod
    def execute_investigation(
        cls,
        db: Session,
        investigation_id: uuid.UUID,
        adapter: Optional[BaseLLMAdapter] = None
    ) -> ForensicInvestigation:
        """
        Synchronous wrapper for execution within RQ background workers.
        """
        try:
            return asyncio.run(cls.execute_investigation_async(db, investigation_id, adapter))
        except RuntimeError:
            # Handle case where an event loop is already running in this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    cls.execute_investigation_async(db, investigation_id, adapter)
                )
            finally:
                loop.close()

    @classmethod
    def get_investigation(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        investigation_id: uuid.UUID
    ) -> ForensicInvestigation:
        """
        Retrieves a forensic investigation enforcing strict tenant scoping.
        """
        stmt = select(ForensicInvestigation).where(
            and_(
                ForensicInvestigation.id == investigation_id,
                ForensicInvestigation.tenant_id == tenant_id
            )
        )
        inv = db.execute(stmt).scalar_one_or_none()
        if not inv:
            raise ResourceNotFoundError(f"Forensic investigation {investigation_id} not found.")
        return inv

    @classmethod
    def list_investigations_for_exception(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        exception_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> List[ForensicInvestigation]:
        """
        Lists all historical investigations for a specific exception and tenant.
        """
        # Confirm exception exists for tenant
        LeakageForensicReader.get_exception(db, tenant_id, exception_id)

        stmt = (
            select(ForensicInvestigation)
            .where(
                and_(
                    ForensicInvestigation.tenant_id == tenant_id,
                    ForensicInvestigation.exception_id == exception_id
                )
            )
            .order_by(desc(ForensicInvestigation.created_at))
            .offset(skip)
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())
