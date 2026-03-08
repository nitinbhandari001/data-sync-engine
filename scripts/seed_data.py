"""Seed all 3 mock connectors with consistent cross-system data."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.connectors.airtable import AirtableConnector
from src.connectors.quickbooks import QuickBooksConnector
from src.connectors.shopify import ShopifyConnector
from src.models import EntityType


async def seed():
    shopify = ShopifyConnector()
    airtable = AirtableConnector()
    qb = QuickBooksConnector()

    # Shared customers (same email in all 3 systems)
    shared_emails = ["shared1@example.com", "shared2@example.com", "shared3@example.com"]
    for i, email in enumerate(shared_emails):
        cid = f"SHARED-{i+1}"
        await shopify.push_record(EntityType.CUSTOMER, {
            "customer_id": cid, "email": email,
            "first_name": f"Shared{i+1}", "last_name": "User",
            "phone": f"555-000{i+1}",
        })
        await airtable.push_record(EntityType.CONTACT, {
            "contact_id": cid, "Name": f"Shared{i+1} User",
            "Email": email, "Company": "SharedCo",
            "Phone": f"555-000{i+1}",
        })
        await qb.push_record(EntityType.CUSTOMER, {
            "customer_id": cid, "DisplayName": f"Shared{i+1} User",
            "PrimaryEmailAddr": email, "CompanyName": "SharedCo",
        })

    print(f"Seeded {len(shared_emails)} shared customers across all 3 systems")
    print(f"Shopify: {len(shopify._orders)} orders, {len(shopify._customers)} customers")
    print(f"Airtable: {len(airtable._contacts)} contacts, {len(airtable._order_log)} order_log")
    print(f"QuickBooks: {len(qb._invoices)} invoices, {len(qb._customers)} customers")


if __name__ == "__main__":
    asyncio.run(seed())
