import json
import uuid
import hashlib
from decimal import Decimal
from datetime import datetime, date, timezone
from typing import Any, Dict, Optional


def serialize_canonical_value(val: Any) -> Any:
    """
    Recursively formats all data types into strict deterministic canonical forms.
    Guarantees arbitrary precision Decimal preservation, enforces Numeric(18, 4) bounds,
    and rejects floating-point values and non-finite decimals.
    """
    # 1. Decimal Handling (Strict Arbitrary Precision NUMERIC(18, 4))
    if isinstance(val, Decimal):
        if not val.is_finite():
            raise ValueError(f"Non-finite Decimal '{val}' is strictly prohibited in financial evidence payloads.")
        
        # Scale Check: Must fit within 4 decimal places without loss
        quantized = val.quantize(Decimal("0.0001"))
        if val != quantized:
            raise ValueError(
                f"Decimal '{val}' exceeds maximum supported scale of 4 decimal places (scale loss would occur)."
            )
        
        # Precision Check: Total digits cannot exceed 18
        digits_count = len(val.as_tuple().digits)
        if digits_count > 18:
            raise ValueError(
                f"Decimal '{val}' has {digits_count} digits, exceeding maximum supported precision of 18 digits."
            )
        
        return f"{val:.4f}"

    # 2. Float Rejection (Absolute Zero-Tolerance in Financial Evidence)
    if isinstance(val, float):
        raise TypeError(
            f"Floating-point value '{val}' detected in evidence payload. "
            "Floats are strictly prohibited in financial calculations and evidence serialization to prevent IEEE 754 precision drift. "
            "Use Decimal or fixed-scale string representation."
        )

    # 3. Datetime and Date Handling
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        else:
            val = val.astimezone(timezone.utc)
        return val.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    if isinstance(val, date):
        return val.isoformat()

    # 4. UUID Handling
    if isinstance(val, uuid.UUID):
        return str(val).lower()

    # 5. Dictionary Key Normalization & Collision Defense
    if isinstance(val, dict):
        normalized: Dict[str, Any] = {}
        for k, v in val.items():
            k_str = str(k)
            if k_str in normalized:
                raise ValueError(f"Dictionary key collision detected on normalized key '{k_str}'.")
            normalized[k_str] = serialize_canonical_value(v)
        return {k: normalized[k] for k in sorted(normalized.keys())}

    # 6. List and Tuple Handling
    if isinstance(val, (list, tuple)):
        return [serialize_canonical_value(item) for item in val]

    # 7. Primitives
    if isinstance(val, (bool, int, str)) or val is None:
        return val

    raise TypeError(f"Unsupported data type '{type(val).__name__}' in canonical evidence serialization.")


def canonical_json_dumps(val: Any) -> str:
    """
    Serializes any supported Python data structure into a deterministic compact JSON string.
    """
    canonical_val = serialize_canonical_value(val)
    return json.dumps(
        canonical_val,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True
    )


def generate_evidence_fingerprint(
    evidence_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    details: Optional[Dict[str, Any]]
) -> str:
    """
    Computes a deterministic SHA-256 fingerprint over the semantic content
    of an evidence item, separating content identity from run or batch provenance.
    """
    canonical_dict = {
        "details": serialize_canonical_value(details or {}),
        "entity_id": str(entity_id).lower(),
        "entity_type": entity_type.strip().lower(),
        "evidence_type": evidence_type.strip().upper(),
    }

    # Compact JSON: sorted keys, no whitespace around separators
    serialized_bytes = json.dumps(
        canonical_dict,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True
    ).encode("utf-8")

    return hashlib.sha256(serialized_bytes).hexdigest()
