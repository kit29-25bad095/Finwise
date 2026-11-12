from datetime import datetime, date, time, timedelta, timezone
from enum import Enum
from typing import Set, Optional, Dict, Any, Tuple


# Indian Standard Time (UTC+05:30)
IST = timezone(timedelta(hours=5, minutes=30))


def normalize_to_ist(dt: datetime) -> datetime:
    """
    Normalizes datetime to Indian Standard Time (IST, UTC+05:30).
    Handles:
    - Timezone-aware datetimes (UTC or non-UTC offsets): converts directly to IST via .astimezone(IST).
    - Naive datetimes: In accordance with Finora canonical storage (all timestamps persisted as UTC),
      naive datetimes originating from SQLite deserialization are safely assigned UTC and converted to IST.
    """
    if dt.tzinfo is None:
        # SQLite deserialization strips tzinfo from DateTime(timezone=True)
        return dt.replace(tzinfo=timezone.utc).astimezone(IST)
    return dt.astimezone(IST)


class CalendarType(str, Enum):
    BANK_CLEARING = "BANK_CLEARING"
    GATEWAY_STANDARD = "GATEWAY_STANDARD"
    EVERYDAY_24X7 = "EVERYDAY_24X7"


# Tier 1 Statutory National Holidays (Fixed Solar Dates under Section 25, Negotiable Instruments Act, 1881)
# Universal across Indian banking clearing, RTGS, and standard bank branches.
STATUTORY_NATIONAL_HOLIDAYS: Set[Tuple[int, int]] = {
    (1, 26),  # Republic Day
    (8, 15),  # Independence Day
    (10, 2),  # Mahatma Gandhi Jayanti
}


def is_statutory_national_holiday(d: date) -> bool:
    """
    Returns True if date is one of India's three statutory national holidays (fixed solar dates).
    """
    return (d.month, d.day) in STATUTORY_NATIONAL_HOLIDAYS


# Provisional reference bank holidays (for test defaults and bank clearing fallbacks)
PROVISIONAL_BANK_HOLIDAYS_2026: Set[date] = {
    date(2026, 1, 26),  # Republic Day (Statutory)
    date(2026, 3, 4),   # Holi (Phalguna Purnima Dhuleti)
    date(2026, 4, 1),   # Annual Bank Account Closing
    date(2026, 4, 2),   # Mahavir Jayanti
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day / May Day
    date(2026, 8, 15),  # Independence Day (Statutory)
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti (Statutory)
    date(2026, 10, 20), # Dussehra
    date(2026, 11, 8),  # Diwali Laxmi Pujan
    date(2026, 11, 10), # Diwali Balipratipada
    date(2026, 11, 24), # Guru Nanak Jayanti
    date(2026, 12, 25), # Christmas
}


class BankingCalendarService:
    """
    Deterministic Banking Calendar & Clearing Window Service.
    Enforces distinct operational rules across clearing rails:
    - BANK_CLEARING: Closed on Sundays, 2nd and 4th Saturdays, statutory national holidays, and RBI bank holidays.
    - GATEWAY_STANDARD: Closed on Saturdays and Sundays (standard 5-day merchant clearing cycle).
      Observes provider-specific maintenance/holidays; does NOT inherit commercial bank closures.
    - EVERYDAY_24X7: Open every calendar day (continuous UPI/IMPS rails).
      Generic bank and national holidays do NOT close this rail; closes only on explicit provider restrictions.
    """

    @classmethod
    def is_second_or_fourth_saturday(cls, d: date) -> bool:
        """
        Determines if a Saturday is the 2nd or 4th Saturday of the month
        under RBI regulations (closed for banking clearing).
        1st week: 1-7, 2nd week: 8-14, 3rd week: 15-21, 4th week: 22-28, 5th week: 29-31.
        """
        if d.weekday() != 5:  # 5 = Saturday
            return False
        day = d.day
        return (8 <= day <= 14) or (22 <= day <= 28)

    @classmethod
    def is_business_day(
        cls,
        d: date,
        calendar_type: CalendarType = CalendarType.BANK_CLEARING,
        provider_holidays: Optional[Set[date]] = None,
        bank_holidays: Optional[Set[date]] = None,
        custom_holidays: Optional[Set[date]] = None,
    ) -> bool:
        """
        Returns True if the date is an operating business day under the selected calendar profile.
        A calendar profile's explicit operating rules take precedence over global holiday checks.
        """
        # Backward compatibility: if custom_holidays passed without specific sets
        effective_provider_holidays = provider_holidays if provider_holidays is not None else custom_holidays
        effective_bank_holidays = bank_holidays if bank_holidays is not None else custom_holidays

        # 1. EVERYDAY_24X7: Open every calendar day unless explicitly restricted for this rail
        if calendar_type == CalendarType.EVERYDAY_24X7:
            if effective_provider_holidays and d in effective_provider_holidays:
                return False
            return True

        # 2. GATEWAY_STANDARD: Closed on Saturdays and Sundays (5-day week)
        if calendar_type == CalendarType.GATEWAY_STANDARD:
            if d.weekday() in (5, 6):  # Saturday or Sunday
                return False
            if effective_provider_holidays and d in effective_provider_holidays:
                return False
            return True

        # 3. BANK_CLEARING: Closed on Sundays and 2nd/4th Saturdays; 1st/3rd/5th Saturdays open
        if d.weekday() == 6:  # Sunday
            return False
        if cls.is_second_or_fourth_saturday(d):
            return False
        if is_statutory_national_holiday(d):
            return False
        holidays = effective_bank_holidays if effective_bank_holidays is not None else PROVISIONAL_BANK_HOLIDAYS_2026
        return d not in holidays

    @classmethod
    def add_business_days(
        cls,
        start_date: date,
        business_days: int,
        calendar_type: CalendarType = CalendarType.BANK_CLEARING,
        provider_holidays: Optional[Set[date]] = None,
        bank_holidays: Optional[Set[date]] = None,
        custom_holidays: Optional[Set[date]] = None,
    ) -> date:
        """
        Adds N business days to start_date according to the calendar profile.
        """
        if business_days <= 0:
            return start_date

        current_date = start_date
        added = 0
        while added < business_days:
            current_date += timedelta(days=1)
            if cls.is_business_day(
                current_date,
                calendar_type=calendar_type,
                provider_holidays=provider_holidays,
                bank_holidays=bank_holidays,
                custom_holidays=custom_holidays,
            ):
                added += 1

        return current_date

    @classmethod
    def parse_cutoff_time(cls, cutoff_str: str) -> time:
        """
        Parses HH:MM string into datetime.time. Defaults to 23:00 if invalid.
        """
        try:
            parts = cutoff_str.strip().split(":")
            return time(hour=int(parts[0]), minute=int(parts[1]))
        except Exception:
            return time(hour=23, minute=0)

    @classmethod
    def get_day_zero(
        cls,
        captured_at: datetime,
        cutoff_time_str: str = "23:00",
        calendar_type: CalendarType = CalendarType.GATEWAY_STANDARD,
        provider_holidays: Optional[Set[date]] = None,
        bank_holidays: Optional[Set[date]] = None,
        custom_holidays: Optional[Set[date]] = None,
    ) -> date:
        """
        Determines Day 0 based on capture timestamp normalized to IST and provider cutoff time:
        - If capture is before cutoff:
            - If today is an active business day under calendar_type: Day 0 = capture_date.
            - Else: Day 0 = next business day under calendar_type.
        - If capture is at or after cutoff (exact >= boundary):
            - Day 0 advances to the next business day under calendar_type.
        """
        ist_dt = normalize_to_ist(captured_at)
        cutoff = cls.parse_cutoff_time(cutoff_time_str)
        capture_date = ist_dt.date()
        capture_time = ist_dt.time()

        if capture_time < cutoff:
            if cls.is_business_day(
                capture_date,
                calendar_type=calendar_type,
                provider_holidays=provider_holidays,
                bank_holidays=bank_holidays,
                custom_holidays=custom_holidays,
            ):
                return capture_date
            else:
                return cls.add_business_days(
                    capture_date,
                    1,
                    calendar_type=calendar_type,
                    provider_holidays=provider_holidays,
                    bank_holidays=bank_holidays,
                    custom_holidays=custom_holidays,
                )
        else:
            # At or past cutoff: strictly advances to next business day
            return cls.add_business_days(
                capture_date,
                1,
                calendar_type=calendar_type,
                provider_holidays=provider_holidays,
                bank_holidays=bank_holidays,
                custom_holidays=custom_holidays,
            )

    @classmethod
    def calculate_settlement_due_date(
        cls,
        captured_at: datetime,
        turnaround_days: int = 2,
        cutoff_time_str: str = "23:00",
        calendar_type: CalendarType = CalendarType.GATEWAY_STANDARD,
        provider_holidays: Optional[Set[date]] = None,
        bank_holidays: Optional[Set[date]] = None,
        custom_holidays: Optional[Set[date]] = None,
    ) -> date:
        """
        Calculates contractual SettlementDueDate:
        SettlementDueDate = AddBusinessDays(Day_0, T_contract, Calendar)
        """
        day_0 = cls.get_day_zero(
            captured_at=captured_at,
            cutoff_time_str=cutoff_time_str,
            calendar_type=calendar_type,
            provider_holidays=provider_holidays,
            bank_holidays=bank_holidays,
            custom_holidays=custom_holidays,
        )
        return cls.add_business_days(
            start_date=day_0,
            business_days=turnaround_days,
            calendar_type=calendar_type,
            provider_holidays=provider_holidays,
            bank_holidays=bank_holidays,
            custom_holidays=custom_holidays,
        )
