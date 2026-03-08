from __future__ import annotations
import hashlib, json
from datetime import datetime, timedelta
from uuid import uuid4
from faker import Faker
from ..models import EntityType, SyncRecord
from .base import Connector

fake = Faker()
Faker.seed(42)

def _checksum(data: dict) -> str:
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


class ShopifyConnector(Connector):
    name = "shopify"

    def __init__(self) -> None:
        self._orders: dict[str, dict] = {}
        self._products: dict[str, dict] = {}
        self._customers: dict[str, dict] = {}
        self._seed()

    def _seed(self) -> None:
        base_time = datetime(2024, 1, 1)
        for i in range(100):
            oid = f"SH-ORD-{1000+i}"
            cust_email = fake.email()
            self._orders[oid] = {
                "order_number": oid,
                "customer_email": cust_email,
                "customer_name": fake.name(),
                "total_price": str(round(fake.random.uniform(20, 2000), 2)),
                "currency": "USD",
                "fulfillment_status": fake.random_element(["fulfilled", "pending", "unfulfilled"]),
                "line_items": [
                    {"title": fake.catch_phrase(), "price": str(round(fake.random.uniform(5, 500), 2)), "quantity": fake.random_int(1, 5)}
                    for _ in range(fake.random_int(1, 4))
                ],
                "created_at": (base_time + timedelta(days=i)).isoformat(),
                "updated_at": (base_time + timedelta(days=i, hours=2)).isoformat(),
            }
        for i in range(30):
            pid = f"SH-PRD-{100+i}"
            self._products[pid] = {
                "product_id": pid,
                "title": fake.catch_phrase(),
                "vendor": fake.company(),
                "price": str(round(fake.random.uniform(10, 500), 2)),
                "inventory_quantity": fake.random_int(0, 200),
                "status": fake.random_element(["active", "draft"]),
                "updated_at": (base_time + timedelta(days=i*3)).isoformat(),
            }
        for i in range(50):
            cid = f"SH-CUST-{500+i}"
            self._customers[cid] = {
                "customer_id": cid,
                "email": fake.email(),
                "first_name": fake.first_name(),
                "last_name": fake.last_name(),
                "phone": fake.phone_number(),
                "orders_count": fake.random_int(0, 20),
                "updated_at": (base_time + timedelta(days=i*2)).isoformat(),
            }

    def _store(self, entity_type: EntityType) -> dict[str, dict]:
        return {
            EntityType.ORDER: self._orders,
            EntityType.PRODUCT: self._products,
            EntityType.CUSTOMER: self._customers,
        }[entity_type]

    async def fetch_records(self, entity_type: EntityType, since: datetime | None = None) -> list[SyncRecord]:
        store = self._store(entity_type)
        results = []
        for rid, data in store.items():
            if since and "updated_at" in data:
                updated = datetime.fromisoformat(data["updated_at"])
                if updated <= since:
                    continue
            results.append(SyncRecord(
                entity_type=entity_type,
                source_system=self.name,
                source_id=rid,
                data=data,
                checksum=_checksum(data),
                last_modified=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
            ))
        return results

    async def push_record(self, entity_type: EntityType, data: dict) -> str:
        store = self._store(entity_type)
        rid = data.get("order_number") or data.get("product_id") or data.get("customer_id") or str(uuid4())
        data["updated_at"] = datetime.utcnow().isoformat()
        store[rid] = data
        return rid

    async def get_record(self, entity_type: EntityType, record_id: str) -> SyncRecord | None:
        store = self._store(entity_type)
        data = store.get(record_id)
        if not data:
            return None
        return SyncRecord(
            entity_type=entity_type, source_system=self.name, source_id=record_id,
            data=data, checksum=_checksum(data),
            last_modified=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
        )

    async def get_schema(self, entity_type: EntityType) -> dict:
        schemas = {
            EntityType.ORDER: {"order_number": "str", "customer_email": "str", "total_price": "str", "currency": "str", "fulfillment_status": "str", "line_items": "list", "created_at": "datetime", "updated_at": "datetime"},
            EntityType.PRODUCT: {"product_id": "str", "title": "str", "vendor": "str", "price": "str", "inventory_quantity": "int", "status": "str"},
            EntityType.CUSTOMER: {"customer_id": "str", "email": "str", "first_name": "str", "last_name": "str", "phone": "str"},
        }
        return schemas.get(entity_type, {})

    async def health_check(self) -> bool:
        return True
