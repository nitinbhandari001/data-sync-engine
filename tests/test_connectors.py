import pytest
from datetime import datetime, timedelta
from src.connectors.shopify import ShopifyConnector
from src.connectors.airtable import AirtableConnector
from src.connectors.quickbooks import QuickBooksConnector
from src.models import EntityType


@pytest.mark.asyncio
async def test_shopify_fetch_orders():
    conn = ShopifyConnector()
    records = await conn.fetch_records(EntityType.ORDER)
    assert len(records) == 100
    assert all(r.source_system == "shopify" for r in records)
    assert all(r.checksum for r in records)


@pytest.mark.asyncio
async def test_connector_change_detection():
    conn = ShopifyConnector()
    cutoff = datetime(2024, 6, 1)
    records = await conn.fetch_records(EntityType.ORDER, since=cutoff)
    all_records = await conn.fetch_records(EntityType.ORDER)
    assert len(records) < len(all_records)


@pytest.mark.asyncio
async def test_airtable_push_record():
    conn = AirtableConnector()
    rid = await conn.push_record(EntityType.CONTACT, {
        "contact_id": "TEST-001", "Name": "Alice", "Email": "alice@test.com", "Company": "Test Co"
    })
    assert rid == "TEST-001"
    record = await conn.get_record(EntityType.CONTACT, "TEST-001")
    assert record is not None
    assert record.data["Name"] == "Alice"


@pytest.mark.asyncio
async def test_quickbooks_health_check():
    conn = QuickBooksConnector()
    ok = await conn.health_check()
    assert ok is True
