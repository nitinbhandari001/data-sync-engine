from __future__ import annotations
from dataclasses import dataclass
from ..config import Settings, get_settings
from ..connectors.airtable import AirtableConnector
from ..connectors.quickbooks import QuickBooksConnector
from ..connectors.shopify import ShopifyConnector
from ..reconciliation.reconciler import reconcile
from ..services.ai import AIService
from ..storage.sync_store import SyncStore
from ..sync.scheduler import SyncScheduler


@dataclass
class ServiceContainer:
    shopify: ShopifyConnector
    airtable: AirtableConnector
    quickbooks: QuickBooksConnector
    ai: AIService
    store: SyncStore
    scheduler: SyncScheduler
    settings: Settings


def create_services(settings: Settings | None = None) -> ServiceContainer:
    if settings is None:
        settings = get_settings()

    settings.data_dir.mkdir(parents=True, exist_ok=True)

    return ServiceContainer(
        shopify=ShopifyConnector(),
        airtable=AirtableConnector(),
        quickbooks=QuickBooksConnector(),
        ai=AIService.from_settings(settings),
        store=SyncStore(settings.data_dir),
        scheduler=SyncScheduler(),
        settings=settings,
    )
