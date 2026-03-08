from __future__ import annotations
import hashlib, json
from datetime import datetime, timedelta
from uuid import uuid4
from faker import Faker
from ..models import EntityType, SyncRecord
from .base import Connector

fake = Faker()
Faker.seed(99)

def _checksum(data: dict) -> str:
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


class AirtableConnector(Connector):
    name = "airtable"

    def __init__(self) -> None:
        self._contacts: dict[str, dict] = {}
        self._inventory: dict[str, dict] = {}
        self._order_log: dict[str, dict] = {}
        self._seed()

    def _seed(self) -> None:
        base_time = datetime(2024, 1, 1)
        for i in range(50):
            cid = f"AT-CONT-{i+1}"
            self._contacts[cid] = {
                "contact_id": cid,
                "Name": fake.name(),
                "Email": fake.email(),
                "Company": fake.company(),
                "Phone": fake.phone_number(),
                "Status": fake.random_element(["Active", "Inactive", "Lead"]),
                "Last Order Date": (base_time + timedelta(days=i*5)).strftime("%m/%d/%Y"),
                "Lifetime Value": round(fake.random.uniform(0, 50000), 2),
                "updated_at": (base_time + timedelta(days=i*5)).isoformat(),
            }
        for i in range(30):
            iid = f"AT-INV-{i+1}"
            self._inventory[iid] = {
                "item_id": iid,
                "Product Name": fake.catch_phrase(),
                "SKU": f"SKU-{1000+i}",
                "Quantity": fake.random_int(0, 500),
                "Reorder Point": fake.random_int(10, 50),
                "Unit Cost": round(fake.random.uniform(5, 200), 2),
                "updated_at": (base_time + timedelta(days=i*10)).isoformat(),
            }
        for i in range(80):
            oid = f"AT-LOG-{i+1}"
            self._order_log[oid] = {
                "log_id": oid,
                "Order Number": f"SH-ORD-{1000+i}" if i < 80 else f"EXT-{i}",
                "Customer Email": fake.email(),
                "Total": round(fake.random.uniform(20, 2000), 2),
                "Order Date": (base_time + timedelta(days=i)).strftime("%m/%d/%Y"),
                "Status": fake.random_element(["Shipped", "Processing", "Pending"]),
                "Items": fake.catch_phrase(),
                "updated_at": (base_time + timedelta(days=i, hours=3)).isoformat(),
            }

    def _store(self, entity_type: EntityType) -> dict:
        return {
            EntityType.CONTACT: self._contacts,
            EntityType.INVENTORY_ITEM: self._inventory,
            EntityType.ORDER: self._order_log,
        }.get(entity_type, {})

    async def fetch_records(self, entity_type: EntityType, since: datetime | None = None) -> list[SyncRecord]:
        store = self._store(entity_type)
        results = []
        for rid, data in store.items():
            if since and "updated_at" in data:
                if datetime.fromisoformat(data["updated_at"]) <= since:
                    continue
            results.append(SyncRecord(
                entity_type=entity_type, source_system=self.name, source_id=rid,
                data=data, checksum=_checksum(data),
                last_modified=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
            ))
        return results

    async def push_record(self, entity_type: EntityType, data: dict) -> str:
        store = self._store(entity_type)
        rid = data.get("contact_id") or data.get("log_id") or str(uuid4())
        data["updated_at"] = datetime.utcnow().isoformat()
        store[rid] = data
        return rid

    async def get_record(self, entity_type: EntityType, record_id: str) -> SyncRecord | None:
        data = self._store(entity_type).get(record_id)
        if not data:
            return None
        return SyncRecord(
            entity_type=entity_type, source_system=self.name, source_id=record_id,
            data=data, checksum=_checksum(data),
            last_modified=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
        )

    async def get_schema(self, entity_type: EntityType) -> dict:
        return {EntityType.CONTACT: {"Name": "str", "Email": "str", "Company": "str", "Phone": "str", "Status": "str"}}.get(entity_type, {})

    async def health_check(self) -> bool:
        return True
