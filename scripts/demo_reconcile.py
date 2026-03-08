"""Reconciliation demo."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services import create_services
from src.models import EntityType
from src.reconciliation.reconciler import reconcile
from src.reconciliation.reporter import format_report, save_report


async def main():
    c = create_services()
    print("\n=== Reconciliation Demo ===\n")

    report = await reconcile(
        source=c.shopify, target=c.airtable,
        entity_type=EntityType.ORDER,
        key_field="order_number",
        compare_fields=["order_number"],
    )
    print(format_report(report))
    saved = save_report(report, c.settings.data_dir / "reports")
    print(f"\nReport saved: {saved}")


if __name__ == "__main__":
    asyncio.run(main())
