import hashlib
import uuid
from decimal import Decimal
from typing import Dict, Any, List, Tuple, Optional
from app.models.leakage import LeakageException, LeakageRunException, LeakageExceptionEvidence
from app.services.leakage.evidence_hasher import canonical_json_dumps, serialize_canonical_value
from app.services.forensics.evidence_validator import EvidenceValidator


class EvidenceBundleBuilder:
    """
    Constructs deterministic, immutable evidence bundles for AI forensic analysis.
    Preserves exact Decimal representations as canonical strings and computes SHA-256 bundle fingerprints.
    """

    @classmethod
    def build_bundle(
        cls,
        exception: LeakageException,
        run_id: uuid.UUID,
        snapshot: Optional[LeakageRunException],
        evidence_items: List[LeakageExceptionEvidence],
        reviewer_notes: Optional[str] = None
    ) -> Tuple[Dict[str, Any], str, bool]:
        """
        Builds a canonical evidence bundle dictionary and computes its SHA-256 fingerprint.
        Returns:
            (bundle_dict, bundle_fingerprint_sha256, all_verified_bool)
        """
        # Determine amounts from snapshot (if available) or current exception
        if snapshot:
            expected_amount = snapshot.observed_expected_amount
            actual_amount = snapshot.observed_actual_amount
            leakage_amount = snapshot.observed_leakage_amount
            recoverable_amount = snapshot.observed_recoverable_amount
            status_val = snapshot.observed_status
            severity_val = snapshot.observed_severity
            snapshot_id_str = str(snapshot.id)
            snapshot_quality_val = snapshot.snapshot_quality
        else:
            expected_amount = exception.expected_amount
            actual_amount = exception.actual_amount
            leakage_amount = exception.leakage_amount
            recoverable_amount = exception.recoverable_amount
            status_val = exception.status
            severity_val = exception.severity
            snapshot_id_str = None
            snapshot_quality_val = None

        # Verify evidence items and apply PII minimization
        serialized_evidence: List[Dict[str, Any]] = []
        all_verified = True

        for ev in evidence_items:
            status, reason = EvidenceValidator.verify_evidence_fingerprint(
                evidence=ev,
                expected_tenant_id=exception.tenant_id,
                expected_exception_id=exception.id
            )
            if status != "VERIFIED":
                all_verified = False

            redacted_details = EvidenceValidator.redact_pii(ev.details or {})

            item_data = {
                "evidence_id": str(ev.id),
                "evidence_type": ev.evidence_type,
                "entity_type": ev.entity_type,
                "entity_id": str(ev.entity_id),
                "fingerprint_sha256": ev.fingerprint_sha256,
                "verification_status": status,
                "verification_error": reason,
                "details": redacted_details,
            }
            serialized_evidence.append(item_data)

        # Sort evidence deterministically by evidence_id
        serialized_evidence.sort(key=lambda x: x["evidence_id"])

        # Construct deterministic core payload for fingerprinting
        core_bundle = {
            "exception_id": str(exception.id),
            "tenant_id": str(exception.tenant_id),
            "detection_run_id": str(run_id),
            "detector_type": exception.detector_type,
            "exception_type": exception.exception_type,
            "source_entity_type": exception.source_entity_type,
            "source_reference": exception.source_reference,
            "gateway_name": exception.gateway_name,
            "financial_exposure": {
                "expected_amount": serialize_canonical_value(Decimal(str(expected_amount))),
                "actual_amount": serialize_canonical_value(Decimal(str(actual_amount))),
                "leakage_amount": serialize_canonical_value(Decimal(str(leakage_amount))),
                "recoverable_amount": serialize_canonical_value(Decimal(str(recoverable_amount))),
                "currency": exception.currency,
            },
            "status": status_val,
            "severity": severity_val,
            "snapshot_id": snapshot_id_str,
            "snapshot_quality": snapshot_quality_val,
            "evidence_items": serialized_evidence,
            "reviewer_notes": reviewer_notes or "",
        }

        # Compute deterministic SHA-256 fingerprint over canonical JSON representation
        canonical_json_str = canonical_json_dumps(core_bundle)
        bundle_fingerprint = hashlib.sha256(canonical_json_str.encode("utf-8")).hexdigest()

        # Add bundle fingerprint to the returned bundle snapshot
        core_bundle["bundle_fingerprint"] = bundle_fingerprint
        core_bundle["all_evidence_verified"] = all_verified

        return core_bundle, bundle_fingerprint, all_verified
