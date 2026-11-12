import uuid
from enum import Enum
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func

from app.models.reconciliation import FeeContract, FeeScheduleTier


class ContractResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NO_CONTRACT_CONFIGURED = "NO_CONTRACT_CONFIGURED"
    LINEAGE_AMBIGUITY = "LINEAGE_AMBIGUITY"


class TierResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    TIER_NOT_FOUND = "TIER_NOT_FOUND"
    INSTRUMENT_AMBIGUOUS = "INSTRUMENT_AMBIGUOUS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class ContractResolutionResult:
    status: ContractResolutionStatus
    contract: Optional[FeeContract] = None
    tier: Optional[FeeScheduleTier] = None
    tier_status: TierResolutionStatus = TierResolutionStatus.NOT_APPLICABLE
    anomaly_reason: Optional[str] = None
    conflicting_contracts: List[Dict[str, Any]] = field(default_factory=list)


class ContractResolver:
    """
    Authoritative single-source contract and instrument-tier resolution service
    for Phase 4 revenue leakage detectors.
    Enforces tenant and gateway scoping, contract lineage validation,
    and deterministic instrument-tier mapping.
    """

    @classmethod
    def resolve_contract_and_tier(
        cls,
        db: Session,
        tenant_id: uuid.UUID,
        gateway_name: str,
        capture_date: date,
        payment_method: Optional[str] = None,
        card_type: Optional[str] = None,
        card_network: Optional[str] = None,
    ) -> ContractResolutionResult:
        # 1. Fetch all contracts for tenant and gateway
        norm_gw = (gateway_name or "").strip().upper()
        contracts = db.execute(
            select(FeeContract).where(
                and_(
                    FeeContract.tenant_id == tenant_id,
                    func.upper(FeeContract.gateway_name) == norm_gw,
                )
            )
        ).scalars().all()

        if not contracts:
            return ContractResolutionResult(
                status=ContractResolutionStatus.NO_CONTRACT_CONFIGURED,
                anomaly_reason=f"No fee contract configured for tenant and gateway '{norm_gw}'.",
            )

        # 2. Lineage Validation
        # Check invalid contract date ranges (end_date < start_date)
        invalid_date_contracts = [
            c for c in contracts
            if c.start_date is not None and c.end_date is not None and c.end_date < c.start_date
        ]
        if invalid_date_contracts:
            conflicts = [
                {
                    "contract_id": str(c.id),
                    "contract_name": c.contract_name,
                    "version": c.version,
                    "is_active": c.is_active,
                    "start_date": c.start_date.isoformat(),
                    "end_date": c.end_date.isoformat(),
                }
                for c in invalid_date_contracts
            ]
            first_inv = invalid_date_contracts[0]
            return ContractResolutionResult(
                status=ContractResolutionStatus.LINEAGE_AMBIGUITY,
                anomaly_reason=(
                    f"Contract '{first_inv.contract_name}' has invalid date range: "
                    f"end_date ({first_inv.end_date}) is earlier than start_date ({first_inv.start_date})."
                ),
                conflicting_contracts=conflicts,
            )

        # Check multiple simultaneously active contracts
        active_contracts = [c for c in contracts if c.is_active]
        if len(active_contracts) > 1:
            conflicts = [
                {
                    "contract_id": str(c.id),
                    "contract_name": c.contract_name,
                    "version": c.version,
                    "is_active": c.is_active,
                    "start_date": c.start_date.isoformat() if c.start_date else None,
                    "end_date": c.end_date.isoformat() if c.end_date else None,
                }
                for c in active_contracts
            ]
            return ContractResolutionResult(
                status=ContractResolutionStatus.LINEAGE_AMBIGUITY,
                anomaly_reason=f"Multiple simultaneously active contracts ({len(active_contracts)}) found for gateway '{norm_gw}'.",
                conflicting_contracts=conflicts,
            )

        # Check duplicate version numbers
        version_map: Dict[int, List[FeeContract]] = {}
        for c in contracts:
            version_map.setdefault(c.version, []).append(c)

        duplicate_versions = [v for v, v_list in version_map.items() if len(v_list) > 1]
        if duplicate_versions:
            conflicts = [
                {
                    "contract_id": str(c.id),
                    "contract_name": c.contract_name,
                    "version": c.version,
                    "is_active": c.is_active,
                    "start_date": c.start_date.isoformat() if c.start_date else None,
                    "end_date": c.end_date.isoformat() if c.end_date else None,
                }
                for v in duplicate_versions
                for c in version_map[v]
            ]
            return ContractResolutionResult(
                status=ContractResolutionStatus.LINEAGE_AMBIGUITY,
                anomaly_reason=f"Duplicate contract versions {duplicate_versions} detected for gateway '{norm_gw}'.",
                conflicting_contracts=conflicts,
            )

        # Sort contracts monotonically by version ASC
        sorted_contracts = sorted(contracts, key=lambda c: (c.version, c.start_date))

        # Validate chronological progression and successor boundaries
        effective_intervals: List[Tuple[FeeContract, date, Optional[date]]] = []
        for i, c in enumerate(sorted_contracts):
            eff_start = c.start_date
            explicit_end = c.end_date

            if i + 1 < len(sorted_contracts):
                successor = sorted_contracts[i + 1]
                # Chronological inversion check
                if successor.start_date <= eff_start:
                    conflicts = [
                        {
                            "contract_id": str(x.id),
                            "contract_name": x.contract_name,
                            "version": x.version,
                            "start_date": x.start_date.isoformat(),
                            "end_date": x.end_date.isoformat() if x.end_date else None,
                        }
                        for x in (c, successor)
                    ]
                    return ContractResolutionResult(
                        status=ContractResolutionStatus.LINEAGE_AMBIGUITY,
                        anomaly_reason=(
                            f"Successor contract v{successor.version} start_date ({successor.start_date}) "
                            f"is not strictly after predecessor v{c.version} start_date ({eff_start})."
                        ),
                        conflicting_contracts=conflicts,
                    )

                # Boundary collision check when predecessor has explicit end_date
                if explicit_end is not None and successor.start_date <= explicit_end:
                    conflicts = [
                        {
                            "contract_id": str(x.id),
                            "contract_name": x.contract_name,
                            "version": x.version,
                            "start_date": x.start_date.isoformat(),
                            "end_date": x.end_date.isoformat() if x.end_date else None,
                        }
                        for x in (c, successor)
                    ]
                    return ContractResolutionResult(
                        status=ContractResolutionStatus.LINEAGE_AMBIGUITY,
                        anomaly_reason=(
                            f"Predecessor contract v{c.version} end_date ({explicit_end}) "
                            f"collides with successor v{successor.version} start_date ({successor.start_date})."
                        ),
                        conflicting_contracts=conflicts,
                    )

                # Clamp open-ended predecessor
                if explicit_end is None:
                    eff_end = successor.start_date - timedelta(days=1)
                else:
                    eff_end = explicit_end
            else:
                # Last or sole contract in lineage
                eff_end = explicit_end

            effective_intervals.append((c, eff_start, eff_end))

        # 3. Match contracts covering capture_date
        matching_contracts: List[FeeContract] = []
        for c, eff_start, eff_end in effective_intervals:
            if eff_start <= capture_date:
                if eff_end is None or capture_date <= eff_end:
                    matching_contracts.append(c)

        if len(matching_contracts) > 1:
            conflicts = [
                {
                    "contract_id": str(c.id),
                    "contract_name": c.contract_name,
                    "version": c.version,
                    "start_date": c.start_date.isoformat(),
                    "end_date": c.end_date.isoformat() if c.end_date else None,
                }
                for c in matching_contracts
            ]
            return ContractResolutionResult(
                status=ContractResolutionStatus.LINEAGE_AMBIGUITY,
                anomaly_reason=f"Multiple contracts ({len(matching_contracts)}) encompass capture date {capture_date}.",
                conflicting_contracts=conflicts,
            )

        if len(matching_contracts) == 0:
            return ContractResolutionResult(
                status=ContractResolutionStatus.NO_CONTRACT_CONFIGURED,
                anomaly_reason=f"No contract for gateway '{norm_gw}' covers capture date {capture_date}.",
            )

        selected_contract = matching_contracts[0]

        # 4. Deterministic Instrument Tier Resolution
        tier, tier_status, tier_reason = cls._resolve_tier_deterministic(
            selected_contract,
            payment_method=payment_method,
            card_type=card_type,
            card_network=card_network,
        )

        return ContractResolutionResult(
            status=ContractResolutionStatus.RESOLVED,
            contract=selected_contract,
            tier=tier,
            tier_status=tier_status,
            anomaly_reason=tier_reason,
        )

    @classmethod
    def _resolve_tier_deterministic(
        cls,
        contract: FeeContract,
        payment_method: Optional[str] = None,
        card_type: Optional[str] = None,
        card_network: Optional[str] = None,
    ) -> Tuple[Optional[FeeScheduleTier], TierResolutionStatus, Optional[str]]:
        if not contract.tiers:
            return None, TierResolutionStatus.TIER_NOT_FOUND, f"Contract '{contract.contract_name}' has no tariff tiers configured."

        method = (payment_method or "").strip().upper()
        c_type = (card_type or "").strip().upper()
        network = (card_network or "").strip().upper()

        # Build lookup maps by exact instrument_type
        tier_by_type: Dict[str, FeeScheduleTier] = {}
        for t in contract.tiers:
            tier_by_type[t.instrument_type.strip().upper()] = t

        # 0. Direct exact match check (e.g. CREDIT_STANDARD matching CREDIT_STANDARD)
        # Corporate transactions must not bypass corporate policy via a generic method match.
        if method and method in tier_by_type:
            if c_type in ("CORPORATE", "COMMERCIAL") and method in ("CREDIT_STANDARD", "CREDIT", "CARD", "ALL_CARDS"):
                pass  # Fall through to dedicated corporate resolution logic
            else:
                return tier_by_type[method], TierResolutionStatus.RESOLVED, None

        # UPI Resolution
        if method == "UPI":
            tier = tier_by_type.get("UPI")
            if tier:
                return tier, TierResolutionStatus.RESOLVED, None
            return None, TierResolutionStatus.TIER_NOT_FOUND, "No UPI tariff tier configured in contract."

        # Netbanking Resolution
        if method in ("NETBANKING", "NB"):
            tier = tier_by_type.get("NETBANKING") or tier_by_type.get("NB")
            if tier:
                return tier, TierResolutionStatus.RESOLVED, None
            return None, TierResolutionStatus.TIER_NOT_FOUND, "No Netbanking tariff tier configured in contract."

        # Wallet Resolution
        if method == "WALLET":
            tier = tier_by_type.get("WALLET")
            if tier:
                return tier, TierResolutionStatus.RESOLVED, None
            return None, TierResolutionStatus.TIER_NOT_FOUND, "No Wallet tariff tier configured in contract."

        # Corporate / Commercial Card Resolution check for missing method
        is_corp = c_type in ("CORPORATE", "COMMERCIAL")
        if is_corp and not method:
            return (
                None,
                TierResolutionStatus.INSTRUMENT_AMBIGUOUS,
                "Corporate transaction lacks payment_method; cannot resolve tariff tier without payment method evidence.",
            )

        # Card Resolution
        if method in ("CARD", "CREDIT", "DEBIT"):
            # Check international first
            if network == "INTERNATIONAL":
                if is_corp:
                    intl_corp = (
                        tier_by_type.get("CORPORATE_INTERNATIONAL")
                        or tier_by_type.get("INTERNATIONAL_CORPORATE")
                    )
                    if intl_corp:
                        return intl_corp, TierResolutionStatus.RESOLVED, None
                tier = tier_by_type.get("INTERNATIONAL") or tier_by_type.get("INTERNATIONAL_CARD")
                if tier:
                    return tier, TierResolutionStatus.RESOLVED, None

            # Specific Corporate Card matching: strict evaluation, never silently fall back
            if is_corp:
                # Ambiguity check 1: Contract has separate corporate domestic & international, but network is missing
                has_corp_intl = any(k in tier_by_type for k in ("CORPORATE_INTERNATIONAL", "INTERNATIONAL_CORPORATE"))
                has_corp_dom = any(
                    k in tier_by_type
                    for k in ("CREDIT_CORPORATE", "CORPORATE", "CORPORATE_CARD", "COMMERCIAL", "COMMERCIAL_CARD", "DOMESTIC_CORPORATE")
                )
                if has_corp_intl and has_corp_dom and not network:
                    return (
                        None,
                        TierResolutionStatus.INSTRUMENT_AMBIGUOUS,
                        "Corporate card transaction lacks card_network; cannot determine domestic vs international corporate tier.",
                    )

                # Ambiguity check 2: Contract has separate corporate credit & debit tiers, but method is generic 'CARD'
                has_corp_credit = any(k in tier_by_type for k in ("CREDIT_CORPORATE", "CORPORATE_CREDIT"))
                has_corp_debit = any(k in tier_by_type for k in ("DEBIT_CORPORATE", "CORPORATE_DEBIT"))
                if has_corp_credit and has_corp_debit and method == "CARD":
                    return (
                        None,
                        TierResolutionStatus.INSTRUMENT_AMBIGUOUS,
                        "Corporate card transaction lacks credit/debit distinction under contract with separate corporate credit and debit tiers.",
                    )

                # 1. Dedicated corporate tier
                dedicated_tier = None
                if method == "DEBIT":
                    dedicated_tier = (
                        tier_by_type.get("DEBIT_CORPORATE")
                        or tier_by_type.get("CORPORATE_DEBIT")
                    )
                if not dedicated_tier:
                    dedicated_tier = (
                        tier_by_type.get("CREDIT_CORPORATE")
                        or tier_by_type.get("CORPORATE")
                        or tier_by_type.get("CORPORATE_CARD")
                        or tier_by_type.get("COMMERCIAL")
                        or tier_by_type.get("COMMERCIAL_CARD")
                        or tier_by_type.get("CORPORATE_CREDIT")
                    )

                if dedicated_tier:
                    return dedicated_tier, TierResolutionStatus.RESOLVED, None

                # 2. Explicitly configured corporate inheritance
                inherit_tier = (
                    tier_by_type.get("CORPORATE_INHERIT_STANDARD")
                    or tier_by_type.get("CORPORATE_INHERIT_CREDIT")
                    or tier_by_type.get("CORPORATE_INHERITS_STANDARD")
                    or tier_by_type.get("CORPORATE_INHERITS_CREDIT")
                )
                if inherit_tier:
                    target_tier = (
                        tier_by_type.get("CREDIT_STANDARD")
                        or tier_by_type.get("CREDIT")
                        or tier_by_type.get("CREDIT_CARD")
                        or inherit_tier
                    )
                    return target_tier, TierResolutionStatus.RESOLVED, None

                # Corporate tier absent and standard credit exists or generic card exists:
                # Prohibit silent fallback!
                return (
                    None,
                    TierResolutionStatus.TIER_NOT_FOUND,
                    "No dedicated corporate card tier configured in contract; standard credit fallback prohibited.",
                )

            # Check if contract only has a single generic CARD tier (non-corporate only)
            has_generic_card = "CARD" in tier_by_type or "ALL_CARDS" in tier_by_type
            has_specific_credit = any(k in tier_by_type for k in ("CREDIT", "CREDIT_STANDARD", "CREDIT_CORPORATE"))
            has_specific_debit = any(k in tier_by_type for k in ("DEBIT", "DEBIT_CARD", "DOMESTIC_DEBIT"))

            if has_generic_card and not (has_specific_credit or has_specific_debit):
                tier = tier_by_type.get("CARD") or tier_by_type.get("ALL_CARDS")
                return tier, TierResolutionStatus.RESOLVED, None

            # Specific Debit matching
            if c_type == "DEBIT" or method == "DEBIT":
                tier = (
                    tier_by_type.get("DEBIT")
                    or tier_by_type.get("DEBIT_CARD")
                    or tier_by_type.get("DOMESTIC_DEBIT")
                    or tier_by_type.get("CARD")
                )
                if tier:
                    return tier, TierResolutionStatus.RESOLVED, None
                return None, TierResolutionStatus.TIER_NOT_FOUND, "No Debit Card tariff tier configured in contract."

            # Specific Standard Credit matching
            if c_type in ("CREDIT", "CONSUMER") or method == "CREDIT":
                tier = (
                    tier_by_type.get("CREDIT_STANDARD")
                    or tier_by_type.get("CREDIT")
                    or tier_by_type.get("CREDIT_CARD")
                    or tier_by_type.get("CARD")
                )
                if tier:
                    return tier, TierResolutionStatus.RESOLVED, None
                return None, TierResolutionStatus.TIER_NOT_FOUND, "No Credit Card tariff tier configured in contract."

            # If card_type is missing/unknown and contract has distinct debit/credit tiers
            if not c_type:
                has_corporate_tier = any(
                    k in tier_by_type
                    for k in ("CREDIT_CORPORATE", "CORPORATE", "CORPORATE_CARD", "COMMERCIAL", "COMMERCIAL_CARD", "CORPORATE_CREDIT")
                )
                if (has_specific_credit and has_specific_debit) or (has_corporate_tier and (has_specific_credit or has_specific_debit)):
                    return (
                        None,
                        TierResolutionStatus.INSTRUMENT_AMBIGUOUS,
                        "Card transaction lacks card_type; cannot distinguish instrument tier under contract.",
                    )
                if has_specific_credit and not has_specific_debit:
                    tier = tier_by_type.get("CREDIT_STANDARD") or tier_by_type.get("CREDIT")
                    return tier, TierResolutionStatus.RESOLVED, None
                if has_specific_debit and not has_specific_credit:
                    tier = tier_by_type.get("DEBIT") or tier_by_type.get("DEBIT_CARD")
                    return tier, TierResolutionStatus.RESOLVED, None

            return None, TierResolutionStatus.TIER_NOT_FOUND, f"Unrecognized card combination: method='{method}', type='{c_type}', network='{network}'."

        return None, TierResolutionStatus.TIER_NOT_FOUND, f"No tariff tier found for payment method '{payment_method}'."
