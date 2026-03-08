from __future__ import annotations
import hashlib, json
from datetime import datetime, timedelta
from uuid import uuid4
from faker import Faker
from ..models import EntityType, SyncRecord
from .base import Connector

fake = Faker()
Faker.seed(77)

def _checksum(data: dict) -> str:
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


class QuickBooksConnector(Connector):
    name = "quickbooks"

    def __init__(self) -> None:
        self._invoices: dict[str, dict] = {}
        self._customers: dict[str, dict] = {}
        self._items: dict[str, dict] = {}
        self._seed()

    def _seed(self) -> None:
        base_time = datetime(2024, 1, 1)
        for i in range(45):
            cid = f"QB-CUST-{i+1}"
            self._customers[cid] = {
                "customer_id": cid,
                "DisplayName": fake.name(),
                "CompanyName": fake.company(),
                "PrimaryEmailAddr": fake.email(),
                "PrimaryPhone": fake.phone_number(),
                "Balance": round(fake.random.uniform(0, 10000), 2),
                "updated_at": (base_time + timedelta(days=i*4)).isoformat(),
            }
        for i in range(60):
            inv_id = f"QB-INV-{3000+i}"
            self._invoices[inv_id] = {
                "invoice_id": inv_id,
                "InvoiceNumber": inv_id,
                "CustomerRef": f"QB-CUST-{(i % 45)+1}",
                "TotalAmt": round(fake.random.uniform(50, 5000), 2),
                "DueDate": (base_time + timedelta(days=i+30)).strftime("%Y-%m-%d"),
                "Balance": round(fake.random.uniform(0, 5000), 2),
                "LineItems": [
                    {"Description": fake.catch_phrase(), "Amount": round(fake.random.uniform(10, 1000), 2), "Qty": fake.random_int(1, 10)}
                    for _ in range(fake.random_int(1, 4))
                ],
                "TxnDate": (base_time + timedelta(days=i)).isoformat(),
                "updated_at": (base_time + timedelta(days=i)).isoformat(),
            }
        for i in range(30):
            iid = f"QB-ITEM-{i+1}"
            self._items[iid] = {
                "item_id": iid,
                "Name": fake.catch_phrase(),
                "UnitPrice": round(fake.random.uniform(5, 500), 2),
                "Type": fake.random_element(["Service", "NonInventory", "Inventory"]),
                "updated_at": (base_time + timedelta(days=i*7)).isoformat(),
            }

    def _store(self, entity_type: EntityType) -> dict:
        return {
            EntityType.INVOICE: self._invoices,
            EntityType.CUSTOMER: self._customers,
            EntityType.PRODUCT: self._items,
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
        rid = data.get("invoice_id") or data.get("customer_id") or data.get("item_id") or str(uuid4())
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
        return {EntityType.INVOICE: {"InvoiceNumber": "str", "TotalAmt": "float", "DueDate": "str", "CustomerRef": "str"}}.get(entity_type, {})

    async def health_check(self) -> bool:
        return True
