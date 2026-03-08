"""Demonstrate conflict detection and resolution."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta
from src.services import create_services
from src.models import EntityType, SyncDirection, ConflictStrategy
from src.sync.engine import SyncEngine
from src.sync.conflict_resolver import resolve_last_write_wins, resolve_source_priority
from src.models import Conflict, SyncRecord

MAPPINGS = Path(__file__).parent.parent / "config" / "mappings"


async def main():
    c = create_services()
    print("\n=== Conflict Resolution Demo ===\n")
    now = datetime.utcnow()

    conflict_id = "CONFLICT-CUST-001"
    await c.shopify.push_record(EntityType.CUSTOMER, {
        "customer_id": conflict_id, "email": "conflict@test.com",
        "first_name": "John", "last_name": "Doe",
        "phone": "555-SHOPIFY-NEW",
        "updated_at": now.isoformat(),
    })
    await c.airtable.push_record(EntityType.CONTACT, {
        "contact_id": conflict_id, "Name": "John Doe",
        "Email": "conflict@test.com", "Company": "TestCo",
        "Phone": "555-AIRTABLE-OLD",
        "updated_at": (now - timedelta(hours=2)).isoformat(),
    })
    print(f"Created conflict: customer {conflict_id}")
    print(f"  Shopify phone: 555-SHOPIFY-NEW (newer)")
    print(f"  Airtable phone: 555-AIRTABLE-OLD (older)\n")

    src = SyncRecord(entity_type=EntityType.CUSTOMER, source_system="shopify",
                     source_id=conflict_id, data={"phone": "555-SHOPIFY-NEW"},
                     last_modified=now)
    tgt = SyncRecord(entity_type=EntityType.CUSTOMER, source_system="airtable",
                     source_id=conflict_id, data={"phone": "555-AIRTABLE-OLD"},
                     last_modified=now - timedelta(hours=2))
    conflict = Conflict(entity_type=EntityType.CUSTOMER, source_record=src,
                        target_record=tgt, conflicting_fields=["phone"])

    lww = resolve_last_write_wins(conflict)
    print(f"last_write_wins result: phone = {lww.get('phone')}")

    sp = resolve_source_priority(conflict, priority_fields={"phone": "airtable"})
    print(f"source_priority (airtable wins): phone = {sp.get('phone')}")

    print("\nAI resolution: skipped (no LLM keys in demo)")
    print("\nConflict resolution strategies demonstrated.")


if __name__ == "__main__":
    asyncio.run(main())
