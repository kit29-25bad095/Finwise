from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any, Tuple
from datetime import date

from app.models.reconciliation import FeeContract, FeeScheduleTier
from app.models.canonical import CanonicalPayment


def round_half_up(value: Decimal, places: int = 4) -> Decimal:
    """
    Rounds a Decimal value using standard financial ROUND_HALF_UP.
    """
    fmt = Decimal("10") ** (-places)
    return value.quantize(fmt, rounding=ROUND_HALF_UP)


class FeeCalculationResult:
    def __init__(
        self,
        nominal_capture_amount: Decimal,
        percentage_rate: Decimal,
        unrounded_mdr: Decimal,
        fixed_fee: Decimal,
        base_fee: Decimal,
        gst_rate: Decimal,
        calculated_tax: Decimal,
        expected_total_fee: Decimal,
        expected_total_fee_display: Decimal,
        reported_fee: Decimal,
        reported_tax: Decimal,
        reported_total_fee: Decimal,
        overcharge_delta: Decimal,
        is_overcharge: bool,
        is_rounding_drift: bool,
        tier_applied: Optional[str] = None
    ):
        self.nominal_capture_amount = nominal_capture_amount
        self.percentage_rate = percentage_rate
        self.unrounded_mdr = unrounded_mdr
        self.fixed_fee = fixed_fee
        self.base_fee = base_fee
        self.gst_rate = gst_rate
        self.calculated_tax = calculated_tax
        self.expected_total_fee = expected_total_fee
        self.expected_total_fee_display = expected_total_fee_display
        self.reported_fee = reported_fee
        self.reported_tax = reported_tax
        self.reported_total_fee = reported_total_fee
        self.overcharge_delta = overcharge_delta
        self.is_overcharge = is_overcharge
        self.is_rounding_drift = is_rounding_drift
        self.tier_applied = tier_applied

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nominal_capture_amount": str(self.nominal_capture_amount),
            "percentage_rate": str(self.percentage_rate),
            "unrounded_mdr": str(self.unrounded_mdr),
            "fixed_fee": str(self.fixed_fee),
            "base_fee": str(self.base_fee),
            "gst_rate": str(self.gst_rate),
            "calculated_tax": str(self.calculated_tax),
            "expected_total_fee": str(self.expected_total_fee),
            "expected_total_fee_display": str(self.expected_total_fee_display),
            "reported_fee": str(self.reported_fee),
            "reported_tax": str(self.reported_tax),
            "reported_total_fee": str(self.reported_total_fee),
            "overcharge_delta": str(self.overcharge_delta),
            "is_overcharge": self.is_overcharge,
            "is_rounding_drift": self.is_rounding_drift,
            "tier_applied": self.tier_applied,
        }


class FeeCalculator:
    """
    Contract-driven MDR, GST, and tariff calculator.
    Enforces the approved 6-stage financial rounding architecture.
    """

    @classmethod
    def calculate_payment_fees(
        cls,
        payment: CanonicalPayment,
        contract: Optional[FeeContract] = None,
        fee_tolerance: Decimal = Decimal("0.05")
    ) -> FeeCalculationResult:
        """
        Calculates expected MDR, base fee, GST, and verifies against reported fees.
        """
        capture_amount = payment.captured_amount
        reported_fee = payment.reported_fee or Decimal("0.0000")
        reported_tax = payment.reported_tax or Decimal("0.0000")
        reported_total = reported_fee + reported_tax

        # Default fallback rates if no contract active
        percentage_rate = Decimal("0.020000")  # Standard 2%
        fixed_fee = Decimal("0.0000")
        gst_rate = Decimal("0.180000")          # Standard 18% GST
        min_cap: Optional[Decimal] = None
        max_cap: Optional[Decimal] = None
        tier_applied = "DEFAULT_2_PERCENT"

        if contract and contract.tiers:
            gst_rate = contract.gst_rate
            # Match payment instrument (UPI, DEBIT, CREDIT_STANDARD, etc.)
            matched_tier = cls._resolve_tier(payment, contract)
            if matched_tier:
                percentage_rate = matched_tier.percentage_rate
                fixed_fee = matched_tier.fixed_fee_per_txn
                min_cap = matched_tier.min_fee_cap
                max_cap = matched_tier.max_fee_cap
                tier_applied = matched_tier.instrument_type

        # Stage 1: Nominal capture amount (exact NUMERIC 18, 4)
        nominal_capture = capture_amount

        # Stage 2: Contractual MDR Calculation (ROUND_HALF_UP to 4 decimals)
        unrounded_mdr = round_half_up(nominal_capture * percentage_rate, 4)

        # Stage 3: Base Fee Aggregation and Clamping
        base_fee = unrounded_mdr + fixed_fee
        if min_cap is not None and base_fee < min_cap:
            base_fee = min_cap
        if max_cap is not None and base_fee > max_cap:
            base_fee = max_cap
        base_fee = round_half_up(base_fee, 4)

        # Stage 4: Tax (GST) Calculation (ROUND_HALF_UP to 4 decimals)
        calculated_tax = round_half_up(base_fee * gst_rate, 4)

        # Stage 5: Expected Gateway Total Fee
        expected_total_fee = base_fee + calculated_tax
        # Nominal Invoice Representation (ROUND_HALF_UP to 2 decimals)
        expected_display = round_half_up(expected_total_fee, 2)

        # Stage 6: Overcharge Delta & Tolerance Evaluation
        # delta = (reported_fee + reported_tax) - expected_total_fee
        overcharge_delta = reported_total - expected_total_fee

        is_overcharge = overcharge_delta > fee_tolerance
        is_rounding_drift = (Decimal("0.0000") < overcharge_delta <= fee_tolerance)

        return FeeCalculationResult(
            nominal_capture_amount=nominal_capture,
            percentage_rate=percentage_rate,
            unrounded_mdr=unrounded_mdr,
            fixed_fee=fixed_fee,
            base_fee=base_fee,
            gst_rate=gst_rate,
            calculated_tax=calculated_tax,
            expected_total_fee=expected_total_fee,
            expected_total_fee_display=expected_display,
            reported_fee=reported_fee,
            reported_tax=reported_tax,
            reported_total_fee=reported_total,
            overcharge_delta=overcharge_delta,
            is_overcharge=is_overcharge,
            is_rounding_drift=is_rounding_drift,
            tier_applied=tier_applied
        )

    @staticmethod
    def _resolve_tier(payment: CanonicalPayment, contract: FeeContract) -> Optional[FeeScheduleTier]:
        method = (payment.payment_method or "").upper()
        card_type = (payment.card_type or "").upper()

        # Check for specific tier matching
        for tier in contract.tiers:
            instrument = tier.instrument_type.upper()
            if "UPI" in method and "UPI" in instrument:
                return tier
            if "DEBIT" in method and "DEBIT" in instrument:
                return tier
            if "CREDIT" in method:
                if "CORPORATE" in card_type and "CORPORATE" in instrument:
                    return tier
                if "CREDIT_STANDARD" in instrument or ("CREDIT" in instrument and "CORPORATE" not in instrument):
                    return tier
            if "NETBANKING" in method and "NETBANKING" in instrument:
                return tier

        # Default fallback to first tier if exists
        return contract.tiers[0] if contract.tiers else None
