"""
Finora Phase 7 — Blind Holdout Benchmark Dataset Generator & Evaluator.
Generates an independent, synthetic benchmark containing 500+ realistic transaction scenarios
across Indian D2C e-commerce operations to evaluate matching precision, recall, and financial conservation.
"""

import uuid
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
from typing import Dict, Any, List, Tuple


class SyntheticHoldoutScenario:
    def __init__(
        self,
        scenario_id: str,
        category: str,
        description: str,
        order_amount: Decimal,
        capture_amount: Decimal,
        settlement_amount: Decimal,
        bank_amount: Decimal,
        expected_match_classification: str,
        expected_leakage_category: str = "NONE",
        has_prompt_injection: bool = False,
        is_delayed_settlement: bool = False,
        is_fee_overcharge: bool = False,
        is_duplicate_refund: bool = False,
        is_ambiguous: bool = False,
        is_aggregated: bool = False
    ):
        self.scenario_id = scenario_id
        self.category = category
        self.description = description
        self.order_amount = order_amount
        self.capture_amount = capture_amount
        self.settlement_amount = settlement_amount
        self.bank_amount = bank_amount
        self.expected_match_classification = expected_match_classification
        self.expected_leakage_category = expected_leakage_category
        self.has_prompt_injection = has_prompt_injection
        self.is_delayed_settlement = is_delayed_settlement
        self.is_fee_overcharge = is_fee_overcharge
        self.is_duplicate_refund = is_duplicate_refund
        self.is_ambiguous = is_ambiguous
        self.is_aggregated = is_aggregated


def generate_blind_holdout_scenarios(count: int = 500) -> List[SyntheticHoldoutScenario]:
    """
    Generates a calibrated synthetic holdout benchmark of 500+ realistic cases.
    Categorization:
      - 250 Exact Matches (1:1 standard clean flow)
      - 40 Partial Payments / Split Captures
      - 30 Aggregated Bank Credits (Many-to-One Knapsack)
      - 25 Missing Settlement SLA Breaches (T+4 delay)
      - 25 Uncredited Settlements (Settled on gateway, no bank credit)
      - 30 Contractual Fee Overcharges (MDR drift > ₹0.05)
      - 20 Duplicate or Excess Gateway Refunds
      - 20 Ambiguous Collision Cases (Identical amounts without UTR)
      - 20 Banking Holiday & Weekend Cutoff Cases
      - 15 Legitimate Partial Refunds
      - 15 Chargeback & Rolling Reserve Deductions
      - 10 Malicious Prompt Injection in Narration
    Total = 500 scenarios
    """
    scenarios: List[SyntheticHoldoutScenario] = []

    # 1. Exact Matches (250 items)
    for i in range(1, 251):
        amt = Decimal(str(1000 + i * 25)) + Decimal("0.0000")
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"EXACT-{i:03d}",
            category="EXACT_MATCH",
            description=f"Standard 1:1:1:1 clean reconciliation flow ₹{amt}",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=amt - Decimal("23.6000"),  # Net after standard 2% + 18% GST
            bank_amount=amt - Decimal("23.6000"),
            expected_match_classification="EXACT_MATCH"
        ))

    # 2. Partial Payments (40 items)
    for i in range(1, 41):
        order_amt = Decimal("10000.0000")
        capture_amt = Decimal("6000.0000")
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"PARTIAL-{i:03d}",
            category="PARTIAL_PAYMENT",
            description=f"Partial order payment capture ₹{capture_amt} on ₹{order_amt} order",
            order_amount=order_amt,
            capture_amount=capture_amt,
            settlement_amount=capture_amt - Decimal("141.6000"),
            bank_amount=capture_amt - Decimal("141.6000"),
            expected_match_classification="PARTIAL_MATCH"
        ))

    # 3. Aggregated Bank Credits (30 items)
    for i in range(1, 31):
        amt = Decimal("25000.0000")
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"AGGREGATED-{i:03d}",
            category="AGGREGATED_BANK_CREDIT",
            description="Aggregated RTGS credit matching N settlement batches",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=Decimal("12500.0000"),
            bank_amount=Decimal("25000.0000"),
            expected_match_classification="AGGREGATED_MATCH",
            is_aggregated=True
        ))

    # 4. Missing Settlements (25 items)
    for i in range(1, 26):
        amt = Decimal(str(3000 + i * 50))
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"MISSING-SETL-{i:03d}",
            category="MISSING_SETTLEMENT",
            description="Capture succeeded but gateway settlement overdue beyond contractual SLA",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=Decimal("0.0000"),
            bank_amount=Decimal("0.0000"),
            expected_match_classification="UNMATCHED",
            expected_leakage_category="MISSING_SETTLEMENT",
            is_delayed_settlement=True
        ))

    # 5. Uncredited Settlements (25 items)
    for i in range(1, 26):
        amt = Decimal(str(5000 + i * 100))
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"UNCREDITED-{i:03d}",
            category="UNCREDITED_SETTLEMENT",
            description="Settlement batch settled with UTR but missing in bank statement",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=amt - Decimal("118.0000"),
            bank_amount=Decimal("0.0000"),
            expected_match_classification="UNMATCHED",
            expected_leakage_category="UNCREDITED_SETTLEMENT"
        ))

    # 6. Contractual Fee Overcharges (30 items)
    for i in range(1, 31):
        amt = Decimal(str(8000 + i * 100))
        # Contract expects 2% + 18% GST = ₹188.80 on ₹8,000
        # Gateway charged 3.5% = ₹280.00 + GST = ₹330.40 -> Overcharge ₹141.60
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"OVERCHARGE-{i:03d}",
            category="FEE_OVERCHARGE",
            description="Gateway MDR charged deviates from contractual schedule",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=amt - Decimal("330.4000"),
            bank_amount=amt - Decimal("330.4000"),
            expected_match_classification="EXACT_MATCH",
            expected_leakage_category="FEE_OVERCHARGE",
            is_fee_overcharge=True
        ))

    # 7. Duplicate/Excess Refunds (20 items)
    for i in range(1, 21):
        amt = Decimal("4000.0000")
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"DUP-REFUND-{i:03d}",
            category="DUPLICATE_REFUND",
            description="Duplicate gateway refund executed for same cancellation",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=amt - Decimal("94.4000"),
            bank_amount=amt - Decimal("94.4000"),
            expected_match_classification="EXACT_MATCH",
            expected_leakage_category="DUPLICATE_OR_EXCESS_REFUND",
            is_duplicate_refund=True
        ))

    # 8. Ambiguous Collision Cases (20 items)
    for i in range(1, 21):
        amt = Decimal("15000.0000")
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"AMBIGUOUS-{i:03d}",
            category="AMBIGUOUS_COLLISION",
            description="Equal amount settlement candidates without distinctive UTR",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=amt - Decimal("354.0000"),
            bank_amount=amt - Decimal("354.0000"),
            expected_match_classification="AMBIGUOUS_MATCH",
            is_ambiguous=True
        ))

    # 9. Banking Holidays & Weekend Cutoffs (20 items)
    for i in range(1, 21):
        amt = Decimal(str(6000 + i * 50))
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"HOLIDAY-{i:03d}",
            category="BANKING_HOLIDAY_SCHEDULE",
            description="Settlement spans RBI RTGS holiday and 2nd Saturday",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=amt - Decimal("141.6000"),
            bank_amount=amt - Decimal("141.6000"),
            expected_match_classification="EXACT_MATCH"
        ))

    # 10. Legitimate Partial Refunds (15 items)
    for i in range(1, 16):
        amt = Decimal("7500.0000")
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"LEGIT-REFUND-{i:03d}",
            category="LEGITIMATE_PARTIAL_REFUND",
            description="Partial return of ₹2,500 on ₹7,500 order",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=amt - Decimal("177.0000"),
            bank_amount=amt - Decimal("177.0000"),
            expected_match_classification="EXACT_MATCH"
        ))

    # 11. Chargeback & Rolling Reserve Deductions (15 items)
    for i in range(1, 16):
        amt = Decimal("12000.0000")
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"RESERVE-{i:03d}",
            category="RESERVE_DEDUCTION",
            description="5% rolling reserve deduction applied by gateway",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=amt - Decimal("600.0000") - Decimal("283.2000"),
            bank_amount=amt - Decimal("600.0000") - Decimal("283.2000"),
            expected_match_classification="EXACT_MATCH"
        ))

    # 12. Malicious Prompt Injection in Narration (10 items)
    for i in range(1, 11):
        amt = Decimal("3500.0000")
        scenarios.append(SyntheticHoldoutScenario(
            scenario_id=f"PROMPT-INJ-{i:03d}",
            category="PROMPT_INJECTION",
            description="Malicious prompt injection payload embedded in narration",
            order_amount=amt,
            capture_amount=amt,
            settlement_amount=amt - Decimal("82.6000"),
            bank_amount=amt - Decimal("82.6000"),
            expected_match_classification="EXACT_MATCH",
            has_prompt_injection=True
        ))

    return scenarios
