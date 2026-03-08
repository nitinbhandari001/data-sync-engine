import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock
from src.app import app
import src.app as app_module
from src.services import ServiceContainer
from src.connectors.shopify import ShopifyConnector
from src.connectors.airtable import AirtableConnector
from src.connectors.quickbooks import QuickBooksConnector
from src.services.ai import AIService
from src.storage.sync_store import SyncStore
from src.sync.scheduler import SyncScheduler
from src.config import get_settings


@pytest.fixture
def tmp_container(tmp_path):
    s = get_settings()
    container = ServiceContainer(
        shopify=ShopifyConnector(), airtable=AirtableConnector(),
        quickbooks=QuickBooksConnector(),
        ai=MagicMock(has_providers=False),
        store=SyncStore(tmp_path),
        scheduler=SyncScheduler(),
        settings=s,
    )
    app_module._container = container
    yield container
    app_module._container = None


@pytest.mark.asyncio
async def test_trigger_sync(tmp_container):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/sync/trigger", json={
            "source": "shopify", "target": "airtable", "entity_type": "order"
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["records_fetched"] >= 0


@pytest.mark.asyncio
async def test_list_conflicts(tmp_container):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/conflicts")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_resolve_conflict(tmp_container):
    """Resolve a non-existent conflict → 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/conflicts/nonexistent/resolve",
                                 json={"resolution": {"phone": "555-resolved"}})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reconciliation_endpoint(tmp_container):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/reconcile", json={
            "entity_type": "order", "source": "shopify", "target": "airtable",
            "key_field": "order_number", "compare_fields": ["order_number"],
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "accuracy_pct" in data
    assert data["total_records_checked"] > 0
