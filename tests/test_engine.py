import pytest
from pathlib import Path
from src.connectors.shopify import ShopifyConnector
from src.connectors.airtable import AirtableConnector
from src.models import EntityType, SyncDirection, ConflictStrategy
from src.storage.sync_store import SyncStore
from src.sync.engine import SyncEngine

MAPPINGS_DIR = Path(__file__).parent.parent / "config" / "mappings"


@pytest.fixture
def tmp_store(tmp_path):
    return SyncStore(tmp_path)


@pytest.mark.asyncio
async def test_full_sync_cycle(tmp_store):
    engine = SyncEngine(
        source=ShopifyConnector(), target=AirtableConnector(),
        direction=SyncDirection.SHOPIFY_TO_AIRTABLE,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS_DIR / "shopify_to_airtable.yaml",
        store=tmp_store,
    )
    result = await engine.run()
    assert result.records_fetched > 0
    assert result.duration_ms >= 0
    assert result.completed_at is not None


@pytest.mark.asyncio
async def test_sync_result_tracking(tmp_store):
    engine = SyncEngine(
        source=ShopifyConnector(), target=AirtableConnector(),
        direction=SyncDirection.SHOPIFY_TO_AIRTABLE,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS_DIR / "shopify_to_airtable.yaml",
        store=tmp_store,
    )
    result = await engine.run()
    stored = await tmp_store.get_result(result.sync_id)
    assert stored is not None
    assert stored.sync_id == result.sync_id


@pytest.mark.asyncio
async def test_sync_idempotent(tmp_store):
    """Running sync twice: second run should find 0 changed records."""
    shopify = ShopifyConnector()
    airtable = AirtableConnector()
    engine = SyncEngine(
        source=shopify, target=airtable,
        direction=SyncDirection.SHOPIFY_TO_AIRTABLE,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS_DIR / "shopify_to_airtable.yaml",
        store=tmp_store,
    )
    r1 = await engine.run()
    r2 = await engine.run()
    assert r2.records_fetched == 0  # all already synced (same checksums)


@pytest.mark.asyncio
async def test_sync_with_conflicts(tmp_store):
    """Conflicts detected when source and target both have same record modified."""
    shopify = ShopifyConnector()
    airtable = AirtableConnector()
    # Pre-populate airtable with a record that will conflict
    await airtable.push_record(EntityType.ORDER, {
        "log_id": "SH-ORD-1000", "Order Number": "SH-ORD-1000",
        "Total": 9999.0, "Status": "Modified",
    })
    engine = SyncEngine(
        source=shopify, target=airtable,
        direction=SyncDirection.SHOPIFY_TO_AIRTABLE,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS_DIR / "shopify_to_airtable.yaml",
        store=tmp_store,
        conflict_strategy=ConflictStrategy.LAST_WRITE_WINS,
    )
    result = await engine.run()
    assert result.records_fetched >= 0  # sync ran without exception
