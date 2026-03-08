from __future__ import annotations
import re
from datetime import datetime


_DATE_FORMATS = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y"]


def to_float(value) -> float:
    """Convert string/int/float to float, stripping currency symbols."""
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    cleaned = re.sub(r'[,$\s]', '', str(value))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def to_date(value: str, target_format: str = "%Y-%m-%d") -> str:
    """Normalize date string to target format."""
    value = str(value).strip()[:19]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime(target_format)
        except ValueError:
            continue
    return value


def to_str(value) -> str:
    return str(value) if value is not None else ""


def prefix_str(value: str, prefix: str) -> str:
    if str(value).startswith(prefix):
        return str(value)
    return f"{prefix}{value}"
