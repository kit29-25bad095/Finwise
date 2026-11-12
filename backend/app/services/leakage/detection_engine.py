import time
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func, desc

from app.models.tenant import Tenant
from app.models.user import User
from app.models.audit import AuditLog
from app.models.canonical import (
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalRefund,
    CanonicalOrder,
    CanonicalBankTransaction,
)
from app.models.leakage import (
    LeakageDetectionRun,
    LeakageException,
    LeakageRunException,
    LeakageExceptionEvidence,
    LeakageRunEvidence,
    LeakageExceptionReview,
    DetectorType,
    LeakageExceptionType,
    ExceptionStatus,
    ExceptionSeverity,
    DetectionRunStatus,
    SnapshotQuality,
)
from app.services.leakage.base_detector import LeakageFinding, EvidenceItemDraft
from app.services.leakage.missing_settlement_detector import MissingSettlementDetector
from app.services.leakage.uncredited_settlement_detector import UncreditedSettlementDetector
from app.services.leakage.fee_overcharge_detector import FeeOverchargeDetector
from app.services.leakage.refund_anomaly_detector import RefundAnomalyDetector
from app.services.leakage.evidence_hasher import generate_evidence_fingerprint
from app.services.leakage.clearing_verifier import ClearingVerifier


VALID_LIFECYCLE_TRANSITIONS = {
    ExceptionStatus.OPEN.value: {
        "REVIEW": ExceptionStatus.UNDER_REVIEW.value,
        "CONFIRM": ExceptionStatus.CONFIRMED.value,
        "DISPUTE": ExceptionStatus.DISPUTED.value,
        "MARK_FALSE_POSITIVE": ExceptionStatus.FALSE_POSITIVE.value,
        "CLOSE": ExceptionStatus.CLOSED.value,
    },
    ExceptionStatus.UNDER_REVIEW.value: {
        "CONFIRM": ExceptionStatus.CONFIRMED.value,
        "DISPUTE": ExceptionStatus.DISPUTED.value,
        "MARK_FALSE_POSITIVE": ExceptionStatus.FALSE_POSITIVE.value,
        "CLOSE": ExceptionStatus.CLOSED.value,
    },
    ExceptionStatus.CONFIRMED.value: {
        "DISPUTE": ExceptionStatus.DISPUTED.value,
        "MARK_RECOVERED": ExceptionStatus.RECOVERED.value,
        "RESOLVE": ExceptionStatus.RESOLVED.value,
        "CLOSE": ExceptionStatus.CLOSED.value,
    },
    ExceptionStatus.DISPUTED.value: {
        "MARK_RECOVERED": ExceptionStatus.RECOVERED.value,
        "RESOLVE": ExceptionStatus.RESOLVED.value,
        "MARK_FALSE_POSITIVE": ExceptionStatus.FALSE_POSITIVE.value,
        "CLOSE": ExceptionStatus.CLOSED.value,
    },
    ExceptionStatus.RECOVERED.value: {
        "CLOSE": ExceptionStatus.CLOSED.value,
    },
    ExceptionStatus.RESOLVED.value: {
        "CLOSE": ExceptionStatus.CLOSED.value,
    },
    ExceptionStatus.FALSE_POSITIVE.value: {
        "REOPEN": ExceptionStatus.OPEN.value,
        "CLOSE": ExceptionStatus.CLOSED.value,
    },
    ExceptionStatus.CLOSED.value: {
        "REOPEN": ExceptionStatus.OPEN.value,
    },
}


class DetectionEngine:
    """
    Orchestrator for the Four Deterministic Revenue Leakage Detectors.
    Manages detection runs, coordinates detectors, enforces stable idempotency,
    and governs the complete exception lifecycle and review trail.
    """

    @classmethod
    def run_detection(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        triggered_by_user_id: Optional[uuid.UUID] = None,
        reconciliation_run_id: Optional[uuid.UUID] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> LeakageDetectionRun:
        run = cls.create_run(
            db=db,
            tenant_id=tenant_id,
            user_id=triggered_by_user_id,
            reconciliation_run_id=reconciliation_run_id,
            parameters=parameters,
        )
        return cls.execute_run(db=db, run_id=run.id)

    @classmethod
    def create_run(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        reconciliation_run_id: Optional[uuid.UUID] = None,
        parameters: Optional[Dict[str, Any]] = None
    ) -> LeakageDetectionRun:
        """
        Initializes a new sequential leakage detection run.
        """
        last_run = db.execute(
            select(func.max(LeakageDetectionRun.run_number)).where(
                LeakageDetectionRun.tenant_id == tenant_id
            )
        ).scalar()
        next_run_number = (last_run or 0) + 1

        run_params = {
            "fee_overcharge_tolerance": "0.05",
            "grace_period_days": 1,
            "bank_clearing_window_days": 1,
            "settlement_cutoff_time": "23:00",
            "settlement_delays": {"upi": 1, "card": 2, "netbanking": 2, "default": 2},
        }
        if parameters:
            for k, v in parameters.items():
                run_params[k] = str(v) if isinstance(v, Decimal) else v

        run = LeakageDetectionRun(
            tenant_id=tenant_id,
            run_number=next_run_number,
            status=DetectionRunStatus.PENDING.value,
            is_active=True,
            triggered_by_user_id=user_id,
            reconciliation_run_id=reconciliation_run_id,
            parameters=run_params
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    @classmethod
    def execute_run(cls, db: Session, run_id: uuid.UUID) -> LeakageDetectionRun:
        """
        Executes all 4 deterministic detectors, persists findings and evidence,
        and aggregates quantitative metrics.
        """
        start_time = time.time()
        run = db.get(LeakageDetectionRun, run_id)
        if not run:
            raise ValueError(f"Leakage detection run {run_id} not found.")

        tenant_id = run.tenant_id
        run.status = DetectionRunStatus.IN_PROGRESS.value
        db.commit()

        params = run.parameters or {}

        try:
            # 1. Instantiate the 4 detectors
            detectors = [
                MissingSettlementDetector(),
                UncreditedSettlementDetector(),
                FeeOverchargeDetector(),
                RefundAnomalyDetector(),
            ]

            all_findings: List[LeakageFinding] = []
            for detector in detectors:
                findings = detector.detect(db, tenant_id, params)
                all_findings.extend(findings)

            # Query evaluation counts
            captures_count = db.execute(
                select(func.count(CanonicalPayment.id)).where(CanonicalPayment.tenant_id == tenant_id)
            ).scalar() or 0

            settlements_count = db.execute(
                select(func.count(CanonicalSettlement.id)).where(CanonicalSettlement.tenant_id == tenant_id)
            ).scalar() or 0

            refunds_count = db.execute(
                select(func.count(CanonicalRefund.id)).where(CanonicalRefund.tenant_id == tenant_id)
            ).scalar() or 0

            run.total_captures_evaluated = captures_count
            run.total_settlements_evaluated = settlements_count
            run.total_refunds_evaluated = refunds_count

            # 2. Persist findings with Idempotency Guard
            # Fetch existing active exceptions for tenant
            existing_exceptions = db.execute(
                select(LeakageException).where(
                    and_(
                        LeakageException.tenant_id == tenant_id,
                        LeakageException.status.in_([
                            ExceptionStatus.OPEN.value,
                            ExceptionStatus.UNDER_REVIEW.value,
                            ExceptionStatus.CONFIRMED.value,
                            ExceptionStatus.DISPUTED.value,
                        ])
                    )
                )
            ).scalars().all()

            # Key by (detector_type, exception_type, source_entity_type, source_entity_id)
            existing_map: Dict[Tuple[str, str, str, uuid.UUID], LeakageException] = {
                (e.detector_type, e.exception_type, e.source_entity_type, e.source_entity_id): e
                for e in existing_exceptions
            }

            created_exceptions: List[LeakageException] = []
            matched_keys = set()
            total_leakage = Decimal("0.0000")
            total_recovery = Decimal("0.0000")

            for finding in all_findings:
                key = (
                    finding.detector_type.value,
                    finding.exception_type.value,
                    finding.source_entity_type,
                    finding.source_entity_id,
                )
                matched_keys.add(key)

                if key in existing_map:
                    # Update existing active finding without losing reviewer status
                    exc = existing_map[key]
                    # AUDIT-P4-003: Preserve exc.detection_run_id as immutable origin lineage
                    exc.latest_detection_run_id = run.id
                    exc.expected_amount = finding.expected_amount
                    exc.actual_amount = finding.actual_amount
                    exc.leakage_amount = finding.leakage_amount
                    exc.recoverable_amount = finding.recoverable_amount
                    exc.severity = finding.severity.value
                    exc.severity_reason = finding.severity_reason
                    exc.calculation_breakdown = finding.calculation_breakdown
                    exc.explanation = finding.explanation
                else:
                    # Create new exception
                    exc = LeakageException(
                        tenant_id=tenant_id,
                        detection_run_id=run.id,
                        latest_detection_run_id=run.id,
                        detector_type=finding.detector_type.value,
                        exception_type=finding.exception_type.value,
                        status=ExceptionStatus.OPEN.value,
                        severity=finding.severity.value,
                        severity_reason=finding.severity_reason,
                        source_entity_type=finding.source_entity_type,
                        source_entity_id=finding.source_entity_id,
                        source_reference=finding.source_reference,
                        order_reference=finding.order_reference,
                        gateway_name=finding.gateway_name,
                        expected_amount=finding.expected_amount,
                        actual_amount=finding.actual_amount,
                        leakage_amount=finding.leakage_amount,
                        recoverable_amount=finding.recoverable_amount,
                        currency=finding.currency,
                        calculation_breakdown=finding.calculation_breakdown,
                        explanation=finding.explanation,
                        detector_version=finding.detector_version,
                        rule_version=finding.rule_version,
                        contract_id=finding.contract_id,
                        contract_version=finding.contract_version,
                    )
                    db.add(exc)
                    db.flush()

                # AUDIT-P4-003: Point-in-time observation snapshot for this run
                run_obs = db.execute(
                    select(LeakageRunException).where(
                        and_(
                            LeakageRunException.detection_run_id == run.id,
                            LeakageRunException.exception_id == exc.id,
                        )
                    )
                ).scalar_one_or_none()
                if not run_obs:
                    run_obs = LeakageRunException(
                        detection_run_id=run.id,
                        exception_id=exc.id,
                        tenant_id=tenant_id,
                        observed_status=exc.status,
                        observed_severity=finding.severity.value,
                        observed_expected_amount=finding.expected_amount,
                        observed_actual_amount=finding.actual_amount,
                        observed_leakage_amount=finding.leakage_amount,
                        observed_recoverable_amount=finding.recoverable_amount,
                        calculation_breakdown=finding.calculation_breakdown,
                        explanation=finding.explanation,
                        snapshot_quality=SnapshotQuality.VERIFIED_AT_EXECUTION.value,
                    )
                    db.add(run_obs)

                # AUDIT-P4-002: Add or reuse evidence items with deterministic SHA-256 fingerprints
                for ev_draft in finding.evidence_items:
                    fp = generate_evidence_fingerprint(
                        evidence_type=ev_draft.evidence_type,
                        entity_type=ev_draft.entity_type,
                        entity_id=ev_draft.entity_id,
                        details=ev_draft.details,
                    )
                    ev_item = db.execute(
                        select(LeakageExceptionEvidence).where(
                            and_(
                                LeakageExceptionEvidence.exception_id == exc.id,
                                LeakageExceptionEvidence.fingerprint_sha256 == fp,
                            )
                        )
                    ).scalar_one_or_none()
                    if not ev_item:
                        ev_item = LeakageExceptionEvidence(
                            exception_id=exc.id,
                            tenant_id=tenant_id,
                            fingerprint_sha256=fp,
                            detection_run_id=run.id,
                            evidence_type=ev_draft.evidence_type,
                            entity_type=ev_draft.entity_type,
                            entity_id=ev_draft.entity_id,
                            source_batch_id=ev_draft.source_batch_id,
                            source_row_index=ev_draft.source_row_index,
                            details=ev_draft.details,
                        )
                        db.add(ev_item)
                        db.flush()

                    # Link into LeakageRunEvidence
                    run_ev = db.execute(
                        select(LeakageRunEvidence).where(
                            and_(
                                LeakageRunEvidence.detection_run_id == run.id,
                                LeakageRunEvidence.evidence_id == ev_item.id,
                            )
                        )
                    ).scalar_one_or_none()
                    if not run_ev:
                        run_ev = LeakageRunEvidence(
                            detection_run_id=run.id,
                            evidence_id=ev_item.id,
                            tenant_id=tenant_id,
                        )
                        db.add(run_ev)

                created_exceptions.append(exc)
                total_leakage += finding.leakage_amount
                total_recovery += finding.recoverable_amount

            # AUDIT-P4-006: Clearing Verification for absent exceptions
            executed_types = {
                DetectorType.MISSING_SETTLEMENT,
                DetectorType.UNCREDITED_SETTLEMENT,
                DetectorType.FEE_OVERCHARGE,
                DetectorType.REFUND_ANOMALY,
            }
            for key, existing_exc in existing_map.items():
                if key not in matched_keys and existing_exc.status == ExceptionStatus.OPEN.value:
                    is_cleared = ClearingVerifier.verify_clearing(
                        db=db,
                        exception=existing_exc,
                        executed_detector_types=executed_types,
                    )
                    if is_cleared:
                        existing_exc.status = ExceptionStatus.RESOLVED.value
                        existing_exc.latest_detection_run_id = run.id
                        existing_exc.resolution_notes = (
                            f"Automatically resolved: verified cleared against double-entry allocation graph and statement coverage in run #{run.run_number}."
                        )
                        obs_status = ExceptionStatus.RESOLVED.value
                    else:
                        existing_exc.latest_detection_run_id = run.id
                        if existing_exc.calculation_breakdown is None:
                            existing_exc.calculation_breakdown = {}
                        if isinstance(existing_exc.calculation_breakdown, dict):
                            existing_exc.calculation_breakdown = {
                                **existing_exc.calculation_breakdown,
                                "run_evaluation_status": "ABSENT_WITHOUT_CLEARING_EVIDENCE",
                            }
                        obs_status = existing_exc.status

                    # Record run observation for absent exception
                    run_obs = db.execute(
                        select(LeakageRunException).where(
                            and_(
                                LeakageRunException.detection_run_id == run.id,
                                LeakageRunException.exception_id == existing_exc.id,
                            )
                        )
                    ).scalar_one_or_none()
                    if not run_obs:
                        run_obs = LeakageRunException(
                            detection_run_id=run.id,
                            exception_id=existing_exc.id,
                            tenant_id=tenant_id,
                            observed_status=obs_status,
                            observed_severity=existing_exc.severity,
                            observed_expected_amount=existing_exc.expected_amount,
                            observed_actual_amount=existing_exc.actual_amount,
                            observed_leakage_amount=existing_exc.leakage_amount,
                            observed_recoverable_amount=existing_exc.recoverable_amount,
                            calculation_breakdown=existing_exc.calculation_breakdown,
                            explanation=existing_exc.explanation,
                            snapshot_quality=SnapshotQuality.VERIFIED_AT_EXECUTION.value,
                        )
                        db.add(run_obs)

            # 3. Deactivate previous active runs
            previous_runs = db.execute(
                select(LeakageDetectionRun).where(
                    and_(
                        LeakageDetectionRun.tenant_id == tenant_id,
                        LeakageDetectionRun.id != run.id,
                        LeakageDetectionRun.is_active == True,
                    )
                )
            ).scalars().all()
            for pr in previous_runs:
                pr.is_active = False

            duration_ms = int((time.time() - start_time) * 1000)
            run.status = DetectionRunStatus.COMPLETED.value
            run.exceptions_count = len(created_exceptions)
            run.total_leakage_amount = total_leakage
            run.total_potential_recovery = total_recovery
            run.duration_ms = duration_ms
            run.completed_at = datetime.now(timezone.utc)

            # Audit Log
            audit = AuditLog(
                tenant_id=tenant_id,
                user_id=run.triggered_by_user_id,
                action="LEAKAGE_DETECTION_RUN_COMPLETED",
                target_entity_type="leakage_detection_runs",
                target_entity_id=run.id,
                user_rationale=(
                    f"Executed Leakage Detection Run #{run.run_number} in {duration_ms}ms: "
                    f"identified {len(created_exceptions)} exception(s) with total leakage ₹{total_leakage} "
                    f"and potential recovery ₹{total_recovery}."
                ),
                new_state={
                    "run_number": run.run_number,
                    "status": run.status,
                    "exceptions_count": run.exceptions_count,
                    "total_leakage": str(total_leakage),
                    "total_potential_recovery": str(total_recovery),
                }
            )
            db.add(audit)
            db.commit()
            db.refresh(run)
            return run

        except Exception as e:
            db.rollback()
            run.status = DetectionRunStatus.FAILED.value
            run.error_message = str(e)
            run.duration_ms = int((time.time() - start_time) * 1000)
            db.commit()
            raise

    @classmethod
    def review_exception(
        cls,
        db: Session,
        exception_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reviewer_id: Optional[uuid.UUID],
        action: str,
        notes: Optional[str] = None
    ) -> LeakageException:
        """
        Executes a human review state transition on a leakage exception,
        recording the transition in the immutable review audit ledger.
        """
        exc = db.execute(
            select(LeakageException).where(
                and_(
                    LeakageException.id == exception_id,
                    LeakageException.tenant_id == tenant_id
                )
            )
        ).scalars().first()

        if not exc:
            raise ValueError(f"Leakage exception {exception_id} not found.")

        current_status = exc.status
        action_upper = action.strip().upper()

        transitions = VALID_LIFECYCLE_TRANSITIONS.get(current_status, {})
        if action_upper not in transitions:
            raise ValueError(
                f"Invalid transition action '{action_upper}' for exception in status '{current_status}'. "
                f"Allowed actions: {list(transitions.keys())}."
            )

        new_status = transitions[action_upper]

        # Record review event
        review = LeakageExceptionReview(
            exception_id=exc.id,
            tenant_id=tenant_id,
            reviewer_id=reviewer_id,
            from_status=current_status,
            to_status=new_status,
            action=action_upper,
            notes=notes
        )
        db.add(review)

        # Update exception state
        exc.status = new_status
        exc.reviewed_by_user_id = reviewer_id
        exc.reviewed_at = datetime.now(timezone.utc)
        exc.review_action = action_upper
        if notes:
            exc.resolution_notes = (
                f"{exc.resolution_notes}\n[{action_upper}]: {notes}".strip()
                if exc.resolution_notes
                else f"[{action_upper}]: {notes}"
            )

        # Audit log
        audit = AuditLog(
            tenant_id=tenant_id,
            user_id=reviewer_id,
            action="LEAKAGE_EXCEPTION_REVIEWED",
            target_entity_type="leakage_exceptions",
            target_entity_id=exc.id,
            user_rationale=f"Transitioned exception from '{current_status}' to '{new_status}' via '{action_upper}': {notes or 'No notes'}.",
            new_state={
                "from_status": current_status,
                "to_status": new_status,
                "action": action_upper,
                "exception_id": str(exc.id),
                "leakage_amount": str(exc.leakage_amount),
            }
        )
        db.add(audit)
        db.commit()
        db.refresh(exc)
        return exc
