import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, date, timezone, timedelta
from typing import Optional, Union, Tuple

# Indian Standard Time (UTC+05:30)
IST = timezone(timedelta(hours=5, minutes=30))

FORMULA_PREFIXES = ("=", "+", "-", "@", "|", "%")


def sanitize_csv_cell(value: Optional[str]) -> str:
    """
    DDE / CSV Formula Injection Sanitizer.
    Protects finance teams opening exported CSV files in Excel or Google Sheets.
    If a string starts with formula triggers (=, +, -, @, |, %), escape with leading single quote.
    """
    if value is None:
        return ""
    val_str = str(value).strip()
    if val_str.startswith(FORMULA_PREFIXES):
        # Escape with a leading apostrophe
        return "'" + val_str
    return val_str


def parse_financial_decimal(value: Union[str, int, float, Decimal, None], default: str = "0.0000") -> Decimal:
    """
    Deterministic arbitrary-precision decimal parser.
    Handles Indian thousands comma grouping (e.g., '1,42,80,500.00'), currency symbols ('₹', 'INR'),
    and whitespace. Never delegates to floating-point math.
    """
    if value is None or value == "":
        return Decimal(default)

    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.0001"))

    # Convert to string and clean
    cleaned = str(value).strip()
    # Strip currency symbols and letters
    cleaned = re.sub(r"[₹$€£\sA-Za-z]", "", cleaned)
    # Strip commas used as thousands separators
    cleaned = cleaned.replace(",", "")

    # Handle negative formatted in parentheses e.g. (1200.50) -> -1200.50
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]

    if not cleaned:
        return Decimal(default)

    try:
        dec = Decimal(cleaned)
        return dec.quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid monetary decimal format: '{value}'")


def parse_normalized_datetime(date_str: Union[str, datetime, None]) -> datetime:
    """
    Parses datetime strings with IST (+05:30) fallback and converts to UTC.
    Supported formats:
    - ISO 8601: 2026-11-10T14:30:00Z, 2026-11-10T14:30:00+05:30
    - Standard: 2026-11-10 14:30:00
    - Indian format: 10/11/2026 14:30:00, 10-11-2026 14:30:00
    - Date only: 2026-11-10, 10/11/2026, 10-11-2026
    """
    if not date_str:
        raise ValueError("Datetime string cannot be empty")

    if isinstance(date_str, datetime):
        if date_str.tzinfo is None:
            return date_str.replace(tzinfo=IST).astimezone(timezone.utc)
        return date_str.astimezone(timezone.utc)

    s = str(date_str).strip()

    # Try ISO 8601
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    # Common format attempts
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %I:%M:%S %p",
        "%d-%m-%Y %I:%M:%S %p",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y",
        "%d/%b/%Y",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            # Default naive Indian business dates to IST (+05:30)
            dt = dt.replace(tzinfo=IST)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue

    raise ValueError(f"Unrecognized datetime format: '{date_str}'")


def parse_normalized_date(date_str: Union[str, date, datetime, None]) -> date:
    """
    Extracts date component. For date-only formats, preserves the calendar date
    without timezone shifting.
    """
    if isinstance(date_str, date) and not isinstance(date_str, datetime):
        return date_str
    if not date_str:
        raise ValueError("Date string cannot be empty")
    s = str(date_str).strip()
    date_formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%d/%b/%Y",
        "%m/%d/%Y",
    ]
    for fmt in date_formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    dt = parse_normalized_datetime(date_str)
    return dt.date()
