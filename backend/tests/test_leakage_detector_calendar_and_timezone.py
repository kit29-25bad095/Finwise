import pytest
from datetime import datetime, date, time, timedelta, timezone
from app.services.leakage.calendar_service import (
    BankingCalendarService,
    CalendarType,
    normalize_to_ist,
    IST,
    STATUTORY_NATIONAL_HOLIDAYS,
)


def test_offset_aware_non_utc_timestamp_conversion_to_ist():
    """
    Validates that offset-aware non-UTC timestamps (e.g. UTC+02:00)
    are accurately converted to Indian Standard Time (UTC+05:30).
    """
    tz_cairo = timezone(timedelta(hours=2))
    # 14:30 in Cairo (UTC+2) is 12:30 UTC, which is 18:00 IST (+5:30)
    dt_cairo = datetime(2026, 11, 10, 14, 30, 0, tzinfo=tz_cairo)
    ist_dt = normalize_to_ist(dt_cairo)

    assert ist_dt.tzinfo == IST
    assert ist_dt.date() == date(2026, 11, 10)
    assert ist_dt.time() == time(18, 0, 0)


def test_naive_datetime_handling_from_sqlite_deserialization():
    """
    Validates that naive datetimes (e.g., deserialized by SQLite where timezone
    attributes are stripped from DateTime(timezone=True) columns) are safely
    treated as stored UTC timestamps and converted to IST without a 5.5-hour distortion.
    """
    # Suppose SQLite returns 18:00 naive (which was stored as 18:00 UTC)
    # 18:00 UTC is 23:30 IST on the same day.
    naive_utc_dt = datetime(2026, 11, 10, 18, 0, 0)
    ist_dt = normalize_to_ist(naive_utc_dt)

    assert ist_dt.tzinfo == IST
    assert ist_dt.date() == date(2026, 11, 10)
    assert ist_dt.time() == time(23, 30, 0)


def test_exact_23_00_ist_cutoff_boundary():
    """
    Validates exact cutoff boundaries under 23:00 IST:
    - 22:59:59 IST is strictly before cutoff -> Day 0 is today (if business day).
    - 23:00:00 IST is at cutoff -> Day 0 advances to next business day.
    - 23:00:01 IST is past cutoff -> Day 0 advances to next business day.
    """
    # Tuesday Nov 10, 2026 (a standard business day)
    t_before = datetime(2026, 11, 10, 22, 59, 59, tzinfo=IST)
    t_exact = datetime(2026, 11, 10, 23, 0, 0, tzinfo=IST)
    t_after = datetime(2026, 11, 10, 23, 0, 1, tzinfo=IST)

    day_0_before = BankingCalendarService.get_day_zero(
        t_before,
        cutoff_time_str="23:00",
        calendar_type=CalendarType.GATEWAY_STANDARD,
    )
    day_0_exact = BankingCalendarService.get_day_zero(
        t_exact,
        cutoff_time_str="23:00",
        calendar_type=CalendarType.GATEWAY_STANDARD,
    )
    day_0_after = BankingCalendarService.get_day_zero(
        t_after,
        cutoff_time_str="23:00",
        calendar_type=CalendarType.GATEWAY_STANDARD,
    )

    assert day_0_before == date(2026, 11, 10)
    assert day_0_exact == date(2026, 11, 11)
    assert day_0_after == date(2026, 11, 11)


def test_provider_specific_holiday_isolation():
    """
    A custom holiday configured for a specific provider (e.g. Razorpay scheduled downtime)
    must close only GATEWAY_STANDARD for that provider, while BANK_CLEARING and other
    rails remain completely open on that date.
    """
    test_wednesday = date(2026, 11, 11)
    provider_holidays = {test_wednesday}

    # Under GATEWAY_STANDARD with this provider holiday: closed
    is_gw_open = BankingCalendarService.is_business_day(
        test_wednesday,
        calendar_type=CalendarType.GATEWAY_STANDARD,
        provider_holidays=provider_holidays,
    )
    assert is_gw_open is False

    # Under BANK_CLEARING without this bank holiday: open!
    is_bank_open = BankingCalendarService.is_business_day(
        test_wednesday,
        calendar_type=CalendarType.BANK_CLEARING,
        provider_holidays=provider_holidays,
    )
    assert is_bank_open is True


def test_everyday_24x7_unaffected_by_generic_bank_holidays():
    """
    An EVERYDAY_24X7 rail (e.g., instant UPI/IMPS payouts) must remain open every calendar
    day, completely unaffected by Tier 1 statutory holidays (Jan 26, Aug 15) or bank closures.
    """
    republic_day = date(2026, 1, 26)  # Statutory national holiday
    independence_day = date(2026, 8, 15)  # Statutory national holiday & Saturday
    sunday = date(2026, 11, 8)

    # BANK_CLEARING is closed on all three
    assert BankingCalendarService.is_business_day(republic_day, CalendarType.BANK_CLEARING) is False
    assert BankingCalendarService.is_business_day(independence_day, CalendarType.BANK_CLEARING) is False
    assert BankingCalendarService.is_business_day(sunday, CalendarType.BANK_CLEARING) is False

    # EVERYDAY_24X7 is open on all three!
    assert BankingCalendarService.is_business_day(republic_day, CalendarType.EVERYDAY_24X7) is True
    assert BankingCalendarService.is_business_day(independence_day, CalendarType.EVERYDAY_24X7) is True
    assert BankingCalendarService.is_business_day(sunday, CalendarType.EVERYDAY_24X7) is True


def test_bank_clearing_enforces_rbi_second_fourth_saturday_and_sunday():
    """
    Validates RBI commercial banking clearing rules:
    - Sundays: Always closed.
    - 2nd Saturday (Nov 14, 2026): Closed.
    - 4th Saturday (Nov 28, 2026): Closed.
    - 1st Saturday (Nov 7, 2026): Open.
    - 3rd Saturday (Nov 21, 2026): Open.
    - 5th Saturday (Oct 31, 2026): Open.
    """
    sat_1 = date(2026, 11, 7)
    sat_2 = date(2026, 11, 14)
    sat_3 = date(2026, 11, 21)
    sat_4 = date(2026, 11, 28)
    sat_5 = date(2026, 10, 31)
    sun = date(2026, 11, 15)

    assert BankingCalendarService.is_second_or_fourth_saturday(sat_1) is False
    assert BankingCalendarService.is_second_or_fourth_saturday(sat_2) is True
    assert BankingCalendarService.is_second_or_fourth_saturday(sat_3) is False
    assert BankingCalendarService.is_second_or_fourth_saturday(sat_4) is True
    assert BankingCalendarService.is_second_or_fourth_saturday(sat_5) is False

    assert BankingCalendarService.is_business_day(sat_1, CalendarType.BANK_CLEARING) is True
    assert BankingCalendarService.is_business_day(sat_2, CalendarType.BANK_CLEARING) is False
    assert BankingCalendarService.is_business_day(sat_3, CalendarType.BANK_CLEARING) is True
    assert BankingCalendarService.is_business_day(sat_4, CalendarType.BANK_CLEARING) is False
    assert BankingCalendarService.is_business_day(sat_5, CalendarType.BANK_CLEARING) is True
    assert BankingCalendarService.is_business_day(sun, CalendarType.BANK_CLEARING) is False


def test_gateway_standard_closes_all_saturdays_and_sundays():
    """
    Validates that standard 5-day merchant gateway clearing closes on every Saturday and Sunday.
    """
    sat_1 = date(2026, 11, 7)
    sat_3 = date(2026, 11, 21)
    sun = date(2026, 11, 22)
    mon = date(2026, 11, 23)

    assert BankingCalendarService.is_business_day(sat_1, CalendarType.GATEWAY_STANDARD) is False
    assert BankingCalendarService.is_business_day(sat_3, CalendarType.GATEWAY_STANDARD) is False
    assert BankingCalendarService.is_business_day(sun, CalendarType.GATEWAY_STANDARD) is False
    assert BankingCalendarService.is_business_day(mon, CalendarType.GATEWAY_STANDARD) is True
