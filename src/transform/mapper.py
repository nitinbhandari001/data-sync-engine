from __future__ import annotations
from pathlib import Path
import yaml
import structlog
from ..models import FieldMapping, MappingConfig
from ..exceptions import MappingError

log = structlog.get_logger(__name__)


def load_mapping(mapping_file: Path) -> MappingConfig:
    """Load YAML mapping config from file."""
    if not mapping_file.exists():
        raise MappingError(f"Mapping file not found: {mapping_file}")
    raw = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    return MappingConfig(
        source_system=raw["source_system"],
        target_system=raw["target_system"],
        entity_type=raw["entity_type"],
        mappings=[FieldMapping(**m) for m in raw.get("mappings", [])],
    )


def apply_mapping(source_data: dict, mapping: MappingConfig) -> dict:
    """Apply field mappings to transform source record into target schema."""
    result: dict = {}
    for fm in mapping.mappings:
        value = _get_nested(source_data, fm.source_field)
        if value is None:
            continue
        transformed = _transform(value, fm.transform, fm.transform_config)
        result[fm.target_field] = transformed
    return result


def _get_nested(data: dict, field: str):
    """Support dot notation for nested access: 'customer.email'."""
    parts = field.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _transform(value, transform: str, config: dict):
    if transform == "rename":
        return value
    if transform == "value_map":
        mapping = config.get("mapping", {})
        return mapping.get(str(value), value)
    if transform == "convert":
        if config.get("to_type") == "float":
            try:
                return float(str(value).replace(",", ""))
            except (ValueError, TypeError):
                return value
        if "date_format" in config:
            from datetime import datetime
            fmt = config["date_format"]
            for src_fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
                try:
                    return datetime.strptime(str(value)[:19], src_fmt).strftime(fmt)
                except ValueError:
                    continue
            return value
        if config.get("prefix"):
            return f"{config['prefix']}{value}"
        if config.get("line_items_to_qb"):
            if isinstance(value, list):
                return [{"Description": i.get("title", ""), "Amount": float(i.get("price", 0)), "Qty": i.get("quantity", 1)} for i in value]
        return value
    if transform == "concat":
        if isinstance(value, list):
            field = config.get("extract_field", "")
            sep = config.get("separator", ", ")
            return sep.join(str(item.get(field, "")) for item in value if isinstance(item, dict))
        return value
    return value
