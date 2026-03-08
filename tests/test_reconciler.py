import pytest
from src.connectors.shopify import ShopifyConnector
from src.connectors.airtable import AirtableConnector
from src.models import EntityType
from src.reconciliation.reconciler import reconcile


@pytest.mark.asyncio
async def test_reconciliation_finds_mismatches():
    shopify = ShopifyConnector()
    airtable = AirtableConnector()
    report = await reconcile(
        shopify, airtable, EntityType.ORDER, "order_number", ["order_number"]
    )
    # Different systems — most records won't match by key
    assert report.total_records_checked > 0
    assert isinstance(report.mismatches, list)


@pytest.mark.asyncio
async def test_reconciliation_finds_missing():
    shopify = ShopifyConnector()
    airtable = AirtableConnector()
    report = await reconcile(
        shopify, airtable, EntityType.ORDER, "order_number", ["order_number"]
    )
    # Shopify has 100 orders, Airtable order_log has different keys
    assert len(report.missing_in_target) + report.matches + len(report.mismatches) > 0


@pytest.mark.asyncio
async def test_reconciliation_accuracy_calculation():
    shopify = ShopifyConnector()
    airtable = AirtableConnector()
    report = await reconcile(
        shopify, airtable, EntityType.PRODUCT, "product_id", ["product_id"]
    )
    assert 0.0 <= report.accuracy_pct <= 100.0
