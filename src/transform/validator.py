from __future__ import annotations
import structlog
from ..models import MappingConfig

log = structlog.get_logger(__name__)


def validate_record(record: dict, schema: dict) -> tuple[bool, list[str]]:
    """Validate transformed record against target schema. Returns (is_valid, errors)."""
    errors: list[str] = []
    for field, expected_type in schema.items():
        if field not in record:
            continue  # Missing optional fields are OK
        value = record[field]
        if expected_type == "float" and not isinstance(value, (int, float)):
            try:
                float(value)
            except (TypeError, ValueError):
                errors.append(f"{field}: expected float, got {type(value).__name__}")
        elif expected_type == "int" and not isinstance(value, int):
            errors.append(f"{field}: expected int, got {type(value).__name__}")
    return len(errors) == 0, errors
