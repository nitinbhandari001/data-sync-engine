"""Full sync demonstration."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.services import create_services
from src.models import EntityType, SyncDirection, ConflictStrategy
from src.sync.engine import SyncEngine

MAPPINGS = Path(__file__).parent.parent / "config" / "mappings"


async def main():
    settings = get_settings()
    c = create_services(settings)

    print("\n=== Data Sync Engine Demo ===\n")
    print(f"Shopify:    100 orders, 30 products, 50 customers")
    print(f"Airtable:   50 contacts, 30 inventory, 80 order_log")
    print(f"QuickBooks: 60 invoices, 45 customers, 30 items\n")

    # Sync 1: Shopify -> Airtable (orders)
    print("--- Sync 1: Shopify -> Airtable (orders) ---")
    engine = SyncEngine(
        source=c.shopify, target=c.airtable,
        direction=SyncDirection.SHOPIFY_TO_AIRTABLE,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS / "shopify_to_airtable.yaml",
        store=c.store,
    )
    r1 = await engine.run()
    print(f"  Fetched: {r1.records_fetched}  Created: {r1.records_created}  "
          f"Updated: {r1.records_updated}  Conflicts: {r1.conflicts_found}  "
          f"Duration: {r1.duration_ms:.0f}ms\n")

    # Sync 2: Shopify -> QuickBooks (orders -> invoices)
    print("--- Sync 2: Shopify -> QuickBooks (orders -> invoices) ---")
    engine2 = SyncEngine(
        source=c.shopify, target=c.quickbooks,
        direction=SyncDirection.SHOPIFY_TO_QUICKBOOKS,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS / "shopify_to_quickbooks.yaml",
        store=c.store,
    )
    r2 = await engine2.run()
    print(f"  Fetched: {r2.records_fetched}  Created: {r2.records_created}  "
          f"Updated: {r2.records_updated}  Conflicts: {r2.conflicts_found}  "
          f"Duration: {r2.duration_ms:.0f}ms\n")

    history = await c.store.list_results()
    print(f"Sync history: {len(history)} runs recorded\n")
    print("Done! Start API: uvicorn src.app:app --port 8009")


if __name__ == "__main__":
    asyncio.run(main())
