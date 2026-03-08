from pathlib import Path
import pytest
from src.transform.mapper import load_mapping, apply_mapping
from src.models import MappingConfig, FieldMapping

MAPPINGS_DIR = Path(__file__).parent.parent / "config" / "mappings"


def test_simple_field_rename():
    mapping = MappingConfig(
        source_system="a", target_system="b", entity_type="order",
        mappings=[FieldMapping(source_field="order_number", target_field="Order Number", transform="rename")],
    )
    result = apply_mapping({"order_number": "ORD-001"}, mapping)
    assert result["Order Number"] == "ORD-001"


def test_type_conversion():
    mapping = MappingConfig(
        source_system="a", target_system="b", entity_type="order",
        mappings=[FieldMapping(source_field="total_price", target_field="TotalAmt", transform="convert", transform_config={"to_type": "float"})],
    )
    result = apply_mapping({"total_price": "1,250.00"}, mapping)
    assert result["TotalAmt"] == 1250.0


def test_nested_field_access():
    mapping = MappingConfig(
        source_system="a", target_system="b", entity_type="order",
        mappings=[FieldMapping(source_field="customer.email", target_field="CustomerRef", transform="rename")],
    )
    result = apply_mapping({"customer": {"email": "bob@test.com"}}, mapping)
    assert result["CustomerRef"] == "bob@test.com"


def test_value_mapping():
    mapping = MappingConfig(
        source_system="a", target_system="b", entity_type="order",
        mappings=[FieldMapping(source_field="status", target_field="Status", transform="value_map",
                               transform_config={"mapping": {"fulfilled": "Shipped", "pending": "Processing"}})],
    )
    result = apply_mapping({"status": "fulfilled"}, mapping)
    assert result["Status"] == "Shipped"


def test_yaml_config_loading():
    config = load_mapping(MAPPINGS_DIR / "shopify_to_airtable.yaml")
    assert config.source_system == "shopify"
    assert config.target_system == "airtable"
    assert len(config.mappings) > 0
