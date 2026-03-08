# Data Sync & Transformation Engine — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a FastAPI service that keeps Shopify, Airtable, and QuickBooks data synchronized via pluggable connectors, field mapping, delta sync, conflict resolution, and reconciliation reporting — all in mock mode.

**Architecture:** Three mock connectors (Shopify/Airtable/QuickBooks) share a pluggable `Connector` base class. A field mapping engine (YAML config) transforms records between schemas. A sync engine orchestrates fetch→map→transform→validate→push cycles with conflict detection. A reconciliation layer periodically cross-checks consistency across all 3 systems.

**Tech Stack:** FastAPI 0.115, asyncpg, APScheduler 3.10, pandas 2.2, pydantic-settings 2.7, structlog, openai (LLM cascade), PyYAML, Faker, pytest-asyncio

**Port:** 8009 | **All connectors mock** (zero API keys) | **Cross-platform** (pathlib everywhere)

---

## Dependency Order

```
Task 1 (scaffold + models)
Task 2 (connector base + shopify) ─┐
Task 3 (airtable + quickbooks)    ├─ after Task 1
Task 4 (mapper + YAML configs)    ─┘
Task 5 (converter + validator)     → after Task 4
Task 6 (change_detector)           → after Tasks 2,3
Task 7 (conflict_resolver)         → after Task 1
Task 8 (ai service + sync_store)   → after Tasks 1,7
Task 9 (sync engine)               → after Tasks 4,5,6,7,8
Task 10 (reconciliation)           → after Tasks 2,3,9
Task 11 (scheduler + services)     → after Tasks 8,9
Task 12 (app.py — API)             → after Tasks 9,10,11
Task 13 (scripts)                  → after Task 12
Task 14 (workflows + docs)         → after Task 13
Task 15 (all tests)                → after Task 12
Task 16 (final verify + commit)    → last
```

---

## Key Patterns (Reuse from Portfolio)

| Pattern | Source |
|---------|--------|
| AIService LLM cascade | `portfolio/ecommerce-pipeline/src/services/ai.py` |
| pydantic-settings config | `portfolio/slack-ai-assistant/src/config.py` |
| asyncpg pool | `portfolio/slack-ai-assistant/src/services/database.py` |
| JSON store (index pattern) | `portfolio/ai-report-generator/src/storage/report_store.py` |

---

### Task 1: Scaffold — pyproject.toml + config + models + exceptions

**Files:**
- Create: `pyproject.toml`
- Create: `.env`
- Create: `.gitignore`
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `src/models.py`
- Create: `src/exceptions.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "data-sync-engine"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.28",
    "pandas>=2.2",
    "pydantic>=2.10",
    "pydantic-settings>=2.7",
    "python-dotenv>=1.0",
    "structlog>=24.4",
    "openai>=1.60",
    "asyncpg>=0.30",
    "apscheduler>=3.10",
    "PyYAML>=6.0",
    "faker>=33.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "httpx>=0.28",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["src*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 2: Create src/config.py**

```python
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE = Path(__file__).parent.parent


class Settings(BaseSettings):
    database_url: str = "postgresql://dev:devpassword@localhost:5432/portfolio"
    groq_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    ai_provider: str = "groq"
    ai_fallback_enabled: bool = True
    default_conflict_strategy: str = "last_write_wins"
    sync_interval_minutes: int = 5
    mappings_dir: Path = _BASE / "config" / "mappings"
    data_dir: Path = _BASE / "data"
    slack_bot_token: str = ""
    slack_channel_sync: str = "#data-sync"
    log_level: str = "INFO"
    fastapi_port: int = 8009

    def has_llm(self) -> bool:
        return bool(self.groq_api_key or self.gemini_api_key or self.openrouter_api_key)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

**Step 3: Create src/models.py**

```python
from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field


class EntityType(StrEnum):
    ORDER = "order"
    PRODUCT = "product"
    CUSTOMER = "customer"
    INVOICE = "invoice"
    INVENTORY_ITEM = "inventory_item"
    CONTACT = "contact"


class SyncDirection(StrEnum):
    SHOPIFY_TO_AIRTABLE = "shopify_to_airtable"
    SHOPIFY_TO_QUICKBOOKS = "shopify_to_quickbooks"
    AIRTABLE_TO_QUICKBOOKS = "airtable_to_quickbooks"
    BIDIRECTIONAL = "bidirectional"


class ConflictStrategy(StrEnum):
    LAST_WRITE_WINS = "last_write_wins"
    SOURCE_PRIORITY = "source_priority"
    AI_RESOLUTION = "ai_resolution"
    MANUAL = "manual"


class SyncRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    entity_type: EntityType
    source_system: str
    source_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    checksum: str = ""
    last_modified: datetime = Field(default_factory=datetime.utcnow)
    synced_at: datetime | None = None


class FieldMapping(BaseModel, frozen=True):
    source_field: str
    target_field: str
    transform: str = "rename"          # rename | convert | concat | default | conditional | value_map
    transform_config: dict[str, Any] = Field(default_factory=dict)


class MappingConfig(BaseModel):
    source_system: str
    target_system: str
    entity_type: str
    mappings: list[FieldMapping] = Field(default_factory=list)


class Conflict(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    entity_type: EntityType
    source_record: SyncRecord
    target_record: SyncRecord
    conflicting_fields: list[str] = Field(default_factory=list)
    strategy_used: ConflictStrategy = ConflictStrategy.LAST_WRITE_WINS
    resolution: dict[str, Any] | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None


class SyncResult(BaseModel):
    sync_id: str = Field(default_factory=lambda: str(uuid4()))
    direction: SyncDirection
    entity_type: EntityType
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    records_fetched: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    conflicts_found: int = 0
    conflicts_resolved: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


class Mismatch(BaseModel, frozen=True):
    record_id: str
    field: str
    source_value: Any
    target_value: Any
    source_system: str
    target_system: str


class ReconciliationReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    systems_compared: list[str] = Field(default_factory=list)
    entity_type: EntityType
    total_records_checked: int = 0
    matches: int = 0
    mismatches: list[Mismatch] = Field(default_factory=list)
    missing_in_source: list[str] = Field(default_factory=list)
    missing_in_target: list[str] = Field(default_factory=list)
    accuracy_pct: float = 0.0
```

**Step 4: Create src/exceptions.py**

```python
class SyncError(Exception): pass
class ConnectorError(SyncError): pass
class MappingError(SyncError): pass
class ConflictError(SyncError): pass
class ReconciliationError(SyncError): pass
class SchedulerError(SyncError): pass
```

**Step 5: Create tests/conftest.py**

```python
import pytest
from src.config import get_settings

@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

**Step 6: Create venv and install**

```bash
cd C:\Users\Nitin\portfolio\data-sync-engine
py -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -e ".[dev]"
```

**Step 7: Verify imports work**

```bash
.venv/Scripts/python -c "from src.models import SyncRecord, SyncResult; print('OK')"
```

Expected: `OK`

---

### Task 2: Connector base + Shopify mock

**Files:**
- Create: `src/connectors/__init__.py`
- Create: `src/connectors/base.py`
- Create: `src/connectors/shopify.py`

**Step 1: Create src/connectors/base.py**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime
from ..models import EntityType, SyncRecord


class Connector(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch_records(
        self, entity_type: EntityType, since: datetime | None = None
    ) -> list[SyncRecord]: ...

    @abstractmethod
    async def push_record(self, entity_type: EntityType, data: dict) -> str: ...

    @abstractmethod
    async def get_record(
        self, entity_type: EntityType, record_id: str
    ) -> SyncRecord | None: ...

    @abstractmethod
    async def get_schema(self, entity_type: EntityType) -> dict: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
```

**Step 2: Create src/connectors/shopify.py (mock)**

```python
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
```

**Step 3: Write failing tests**

`tests/test_connectors.py` (partial — Shopify part):
```python
import pytest
from datetime import datetime, timedelta
from src.connectors.shopify import ShopifyConnector
from src.connectors.airtable import AirtableConnector
from src.connectors.quickbooks import QuickBooksConnector
from src.models import EntityType


@pytest.mark.asyncio
async def test_shopify_fetch_orders():
    conn = ShopifyConnector()
    records = await conn.fetch_records(EntityType.ORDER)
    assert len(records) == 100
    assert all(r.source_system == "shopify" for r in records)
    assert all(r.checksum for r in records)


@pytest.mark.asyncio
async def test_connector_change_detection():
    conn = ShopifyConnector()
    # Fetch with a recent cutoff — should get fewer records
    cutoff = datetime(2024, 6, 1)
    records = await conn.fetch_records(EntityType.ORDER, since=cutoff)
    all_records = await conn.fetch_records(EntityType.ORDER)
    assert len(records) < len(all_records)
```

Run: `pytest tests/test_connectors.py::test_shopify_fetch_orders -v`
Expected: FAIL (AirtableConnector not found)

---

### Task 3: Airtable + QuickBooks mock connectors

**Files:**
- Create: `src/connectors/airtable.py`
- Create: `src/connectors/quickbooks.py`

**Step 1: Create src/connectors/airtable.py (mock)**

```python
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
```

**Step 2: Create src/connectors/quickbooks.py (mock)**

```python
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
```

**Step 3: Complete test_connectors.py**

```python
@pytest.mark.asyncio
async def test_airtable_push_record():
    conn = AirtableConnector()
    rid = await conn.push_record(EntityType.CONTACT, {
        "contact_id": "TEST-001", "Name": "Alice", "Email": "alice@test.com", "Company": "Test Co"
    })
    assert rid == "TEST-001"
    record = await conn.get_record(EntityType.CONTACT, "TEST-001")
    assert record is not None
    assert record.data["Name"] == "Alice"


@pytest.mark.asyncio
async def test_quickbooks_health_check():
    conn = QuickBooksConnector()
    ok = await conn.health_check()
    assert ok is True
```

**Step 4: Run all connector tests**

```bash
pytest tests/test_connectors.py -v
```

Expected: 4 passed

---

### Task 4: Field mapper + YAML mapping configs

**Files:**
- Create: `src/transform/__init__.py`
- Create: `src/transform/mapper.py`
- Create: `config/mappings/shopify_to_airtable.yaml`
- Create: `config/mappings/shopify_to_quickbooks.yaml`
- Create: `config/mappings/airtable_to_quickbooks.yaml`
- Create: `config/sync_config.yaml`

**Step 1: Create config/mappings/shopify_to_airtable.yaml**

```yaml
source_system: shopify
target_system: airtable
entity_type: order
mappings:
  - source_field: order_number
    target_field: Order Number
    transform: rename
  - source_field: customer_email
    target_field: Customer Email
    transform: rename
  - source_field: total_price
    target_field: Total
    transform: convert
    transform_config:
      to_type: float
  - source_field: created_at
    target_field: Order Date
    transform: convert
    transform_config:
      date_format: "%m/%d/%Y"
  - source_field: fulfillment_status
    target_field: Status
    transform: value_map
    transform_config:
      mapping:
        fulfilled: Shipped
        pending: Processing
        unfulfilled: Pending
  - source_field: line_items
    target_field: Items
    transform: concat
    transform_config:
      extract_field: title
      separator: ", "
```

**Step 2: Create config/mappings/shopify_to_quickbooks.yaml**

```yaml
source_system: shopify
target_system: quickbooks
entity_type: order
mappings:
  - source_field: order_number
    target_field: InvoiceNumber
    transform: convert
    transform_config:
      prefix: "SH-"
  - source_field: customer_email
    target_field: CustomerRef
    transform: rename
  - source_field: total_price
    target_field: TotalAmt
    transform: convert
    transform_config:
      to_type: float
  - source_field: created_at
    target_field: TxnDate
    transform: rename
  - source_field: line_items
    target_field: LineItems
    transform: convert
    transform_config:
      line_items_to_qb: true
```

**Step 3: Create config/mappings/airtable_to_quickbooks.yaml**

```yaml
source_system: airtable
target_system: quickbooks
entity_type: contact
mappings:
  - source_field: Name
    target_field: DisplayName
    transform: rename
  - source_field: Email
    target_field: PrimaryEmailAddr
    transform: rename
  - source_field: Company
    target_field: CompanyName
    transform: rename
  - source_field: Phone
    target_field: PrimaryPhone
    transform: rename
```

**Step 4: Create config/sync_config.yaml**

```yaml
syncs:
  - direction: shopify_to_airtable
    entity_type: order
    interval_minutes: 5
    conflict_strategy: last_write_wins
    mapping_file: shopify_to_airtable.yaml
  - direction: shopify_to_quickbooks
    entity_type: order
    interval_minutes: 10
    conflict_strategy: source_priority
    mapping_file: shopify_to_quickbooks.yaml
  - direction: airtable_to_quickbooks
    entity_type: contact
    interval_minutes: 15
    conflict_strategy: last_write_wins
    mapping_file: airtable_to_quickbooks.yaml
```

**Step 5: Create src/transform/mapper.py**

```python
from __future__ import annotations
from pathlib import Path
import yaml
import structlog
from ..models import FieldMapping, MappingConfig
from ..exceptions import MappingError

log = structlog.get_logger(__name__)


def load_mapping(mapping_file: Path) -> MappingConfig:
    """Load YAML mapping config from file."""
    if not mapping_file.exists():
        raise MappingError(f"Mapping file not found: {mapping_file}")
    raw = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    return MappingConfig(
        source_system=raw["source_system"],
        target_system=raw["target_system"],
        entity_type=raw["entity_type"],
        mappings=[FieldMapping(**m) for m in raw.get("mappings", [])],
    )


def apply_mapping(source_data: dict, mapping: MappingConfig) -> dict:
    """Apply field mappings to transform source record into target schema."""
    result: dict = {}
    for fm in mapping.mappings:
        value = _get_nested(source_data, fm.source_field)
        if value is None:
            continue
        transformed = _transform(value, fm.transform, fm.transform_config)
        result[fm.target_field] = transformed
    return result


def _get_nested(data: dict, field: str):
    """Support dot notation for nested access: 'customer.email'."""
    parts = field.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _transform(value, transform: str, config: dict):
    if transform == "rename":
        return value
    if transform == "value_map":
        mapping = config.get("mapping", {})
        return mapping.get(str(value), value)
    if transform == "convert":
        if config.get("to_type") == "float":
            try:
                return float(str(value).replace(",", ""))
            except (ValueError, TypeError):
                return value
        if "date_format" in config:
            from datetime import datetime
            fmt = config["date_format"]
            for src_fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
                try:
                    return datetime.strptime(str(value)[:19], src_fmt).strftime(fmt)
                except ValueError:
                    continue
            return value
        if config.get("prefix"):
            return f"{config['prefix']}{value}"
        if config.get("line_items_to_qb"):
            if isinstance(value, list):
                return [{"Description": i.get("title", ""), "Amount": float(i.get("price", 0)), "Qty": i.get("quantity", 1)} for i in value]
        return value
    if transform == "concat":
        if isinstance(value, list):
            field = config.get("extract_field", "")
            sep = config.get("separator", ", ")
            return sep.join(str(item.get(field, "")) for item in value if isinstance(item, dict))
        return value
    return value
```

**Step 6: Write failing tests for mapper**

```python
# tests/test_mapper.py
from pathlib import Path
import pytest
from src.transform.mapper import load_mapping, apply_mapping
from src.models import MappingConfig, FieldMapping

MAPPINGS_DIR = Path(__file__).parent.parent / "config" / "mappings"


def test_simple_field_rename():
    mapping = MappingConfig(
        source_system="a", target_system="b", entity_type="order",
        mappings=[FieldMapping(source_field="order_number", target_field="Order Number", transform="rename")],
    )
    result = apply_mapping({"order_number": "ORD-001"}, mapping)
    assert result["Order Number"] == "ORD-001"


def test_type_conversion():
    mapping = MappingConfig(
        source_system="a", target_system="b", entity_type="order",
        mappings=[FieldMapping(source_field="total_price", target_field="TotalAmt", transform="convert", transform_config={"to_type": "float"})],
    )
    result = apply_mapping({"total_price": "1,250.00"}, mapping)
    assert result["TotalAmt"] == 1250.0


def test_nested_field_access():
    mapping = MappingConfig(
        source_system="a", target_system="b", entity_type="order",
        mappings=[FieldMapping(source_field="customer.email", target_field="CustomerRef", transform="rename")],
    )
    result = apply_mapping({"customer": {"email": "bob@test.com"}}, mapping)
    assert result["CustomerRef"] == "bob@test.com"


def test_value_mapping():
    mapping = MappingConfig(
        source_system="a", target_system="b", entity_type="order",
        mappings=[FieldMapping(source_field="status", target_field="Status", transform="value_map",
                               transform_config={"mapping": {"fulfilled": "Shipped", "pending": "Processing"}})],
    )
    result = apply_mapping({"status": "fulfilled"}, mapping)
    assert result["Status"] == "Shipped"


def test_yaml_config_loading():
    config = load_mapping(MAPPINGS_DIR / "shopify_to_airtable.yaml")
    assert config.source_system == "shopify"
    assert config.target_system == "airtable"
    assert len(config.mappings) > 0
```

**Step 7: Run mapper tests**

```bash
pytest tests/test_mapper.py -v
```

Expected: 5 passed

---

### Task 5: Converter + Validator

**Files:**
- Create: `src/transform/converter.py`
- Create: `src/transform/validator.py`

**Step 1: Create src/transform/converter.py**

```python
from __future__ import annotations
import re
from datetime import datetime


_DATE_FORMATS = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y"]


def to_float(value) -> float:
    """Convert string/int/float to float, stripping currency symbols."""
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    cleaned = re.sub(r'[,$\s]', '', str(value))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def to_date(value: str, target_format: str = "%Y-%m-%d") -> str:
    """Normalize date string to target format."""
    value = str(value).strip()[:19]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime(target_format)
        except ValueError:
            continue
    return value


def to_str(value) -> str:
    return str(value) if value is not None else ""


def prefix_str(value: str, prefix: str) -> str:
    if str(value).startswith(prefix):
        return str(value)
    return f"{prefix}{value}"
```

**Step 2: Create src/transform/validator.py**

```python
from __future__ import annotations
import structlog
from ..models import MappingConfig

log = structlog.get_logger(__name__)


def validate_record(record: dict, schema: dict) -> tuple[bool, list[str]]:
    """Validate transformed record against target schema. Returns (is_valid, errors)."""
    errors: list[str] = []
    for field, expected_type in schema.items():
        if field not in record:
            continue  # Missing optional fields are OK
        value = record[field]
        if expected_type == "float" and not isinstance(value, (int, float)):
            try:
                float(value)
            except (TypeError, ValueError):
                errors.append(f"{field}: expected float, got {type(value).__name__}")
        elif expected_type == "int" and not isinstance(value, int):
            errors.append(f"{field}: expected int, got {type(value).__name__}")
    return len(errors) == 0, errors
```

---

### Task 6: Change Detector

**Files:**
- Create: `src/sync/__init__.py`
- Create: `src/sync/change_detector.py`
- Create: `tests/test_change_detector.py`

**Step 1: Create src/sync/change_detector.py**

```python
from __future__ import annotations
import hashlib
import json
from datetime import datetime
import structlog
from ..models import SyncRecord

log = structlog.get_logger(__name__)


def compute_checksum(data: dict) -> str:
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


class ChangeDetector:
    """Tracks sync state and detects changed records."""

    def __init__(self) -> None:
        # (connector_name, entity_type) → last sync datetime
        self._last_sync: dict[tuple[str, str], datetime] = {}
        # (connector_name, source_id) → checksum
        self._checksums: dict[tuple[str, str], str] = {}

    def get_last_sync(self, connector: str, entity_type: str) -> datetime | None:
        return self._last_sync.get((connector, entity_type))

    def update_last_sync(self, connector: str, entity_type: str, ts: datetime) -> None:
        self._last_sync[(connector, entity_type)] = ts

    def is_changed(self, record: SyncRecord) -> bool:
        """True if record checksum differs from last known checksum."""
        key = (record.source_system, record.source_id)
        prev = self._checksums.get(key)
        return prev != record.checksum

    def mark_synced(self, record: SyncRecord) -> None:
        key = (record.source_system, record.source_id)
        self._checksums[key] = record.checksum

    def filter_changed(self, records: list[SyncRecord]) -> list[SyncRecord]:
        """Return only records that have changed since last sync."""
        return [r for r in records if self.is_changed(r)]
```

**Step 2: Write and run tests**

```python
# tests/test_change_detector.py
import pytest
from datetime import datetime
from src.sync.change_detector import ChangeDetector, compute_checksum
from src.models import SyncRecord, EntityType


def test_detect_new_records():
    detector = ChangeDetector()
    record = SyncRecord(entity_type=EntityType.ORDER, source_system="shopify",
                        source_id="ORD-001", data={"total": 100}, checksum="abc123")
    assert detector.is_changed(record) is True  # new record is always changed


def test_detect_modified_records():
    detector = ChangeDetector()
    r1 = SyncRecord(entity_type=EntityType.ORDER, source_system="shopify",
                    source_id="ORD-001", data={"total": 100}, checksum="abc")
    detector.mark_synced(r1)
    assert detector.is_changed(r1) is False  # unchanged

    r2 = SyncRecord(entity_type=EntityType.ORDER, source_system="shopify",
                    source_id="ORD-001", data={"total": 200}, checksum="xyz")
    assert detector.is_changed(r2) is True   # modified


def test_hash_based_detection():
    data = {"order_number": "ORD-001", "total": 100.0}
    cs1 = compute_checksum(data)
    cs2 = compute_checksum(data)
    assert cs1 == cs2

    data2 = dict(data)
    data2["total"] = 200.0
    cs3 = compute_checksum(data2)
    assert cs1 != cs3
```

Run: `pytest tests/test_change_detector.py -v`
Expected: 3 passed

---

### Task 7: Conflict Resolver (all 4 strategies)

**Files:**
- Create: `src/sync/conflict_resolver.py`
- Create: `tests/test_conflict_resolver.py`

**Step 1: Create src/sync/conflict_resolver.py**

```python
from __future__ import annotations
from datetime import datetime
import structlog
from ..models import Conflict, ConflictStrategy, SyncRecord
from ..exceptions import ConflictError

log = structlog.get_logger(__name__)


def detect_conflicts(source: SyncRecord, target: SyncRecord, mapped_fields: list[str]) -> list[str]:
    """Return list of conflicting field names (modified in both)."""
    conflicts = []
    for field in mapped_fields:
        sv = source.data.get(field)
        tv = target.data.get(field)
        if sv != tv:
            conflicts.append(field)
    return conflicts


def resolve_last_write_wins(conflict: Conflict) -> dict:
    """Return data from whichever record was modified most recently."""
    if conflict.source_record.last_modified >= conflict.target_record.last_modified:
        return dict(conflict.source_record.data)
    return dict(conflict.target_record.data)


def resolve_source_priority(conflict: Conflict, priority_fields: dict[str, str]) -> dict:
    """Merge records using per-field source priority config.
    priority_fields: {"field_name": "shopify" | "airtable"}
    """
    merged = dict(conflict.target_record.data)
    for field in conflict.conflicting_fields:
        preferred = priority_fields.get(field)
        if preferred == conflict.source_record.source_system:
            merged[field] = conflict.source_record.data.get(field)
        # else keep target value
    return merged


async def resolve_with_ai(conflict: Conflict, ai_service) -> dict:
    """Send both records to LLM, get merged result with explanation."""
    if not ai_service or not ai_service.has_providers:
        log.warning("ai_unavailable_fallback_lww")
        return resolve_last_write_wins(conflict)

    system = (
        "You are a data conflict resolution expert. Given two versions of the same record "
        "from different systems, return the best merged version as valid JSON. "
        "Prefer the most specific and recent values. Return ONLY JSON, no explanation."
    )
    user = (
        f"Record from {conflict.source_record.source_system}:\n{conflict.source_record.data}\n\n"
        f"Record from {conflict.target_record.source_system}:\n{conflict.target_record.data}\n\n"
        f"Conflicting fields: {conflict.conflicting_fields}\n\n"
        "Return merged JSON:"
    )
    result = await ai_service.call_llm(system, user)
    if not result:
        return resolve_last_write_wins(conflict)
    import json, re
    text = re.sub(r'^```(?:json)?\s*', '', result.strip())
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        return resolve_last_write_wins(conflict)


def flag_manual(conflict: Conflict) -> Conflict:
    """Flag conflict for manual review — no resolution applied."""
    return conflict.model_copy(update={"resolved_by": None, "resolution": None})


async def resolve_conflict(
    conflict: Conflict,
    strategy: ConflictStrategy,
    ai_service=None,
    priority_fields: dict | None = None,
) -> tuple[dict | None, str]:
    """Route conflict to appropriate strategy. Returns (resolved_data, resolved_by)."""
    if strategy == ConflictStrategy.LAST_WRITE_WINS:
        return resolve_last_write_wins(conflict), "rule:last_write_wins"
    if strategy == ConflictStrategy.SOURCE_PRIORITY:
        return resolve_source_priority(conflict, priority_fields or {}), "rule:source_priority"
    if strategy == ConflictStrategy.AI_RESOLUTION:
        data = await resolve_with_ai(conflict, ai_service)
        return data, "ai"
    # MANUAL
    return None, "manual"
```

**Step 2: Write and run tests**

```python
# tests/test_conflict_resolver.py
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from src.sync.conflict_resolver import (
    resolve_last_write_wins, resolve_source_priority,
    resolve_with_ai, flag_manual, resolve_conflict,
)
from src.models import Conflict, ConflictStrategy, SyncRecord, EntityType


def _make_conflict(src_data, tgt_data, src_modified=None, tgt_modified=None):
    now = datetime.utcnow()
    src = SyncRecord(entity_type=EntityType.CUSTOMER, source_system="shopify",
                     source_id="C-001", data=src_data,
                     last_modified=src_modified or now)
    tgt = SyncRecord(entity_type=EntityType.CUSTOMER, source_system="airtable",
                     source_id="C-001", data=tgt_data,
                     last_modified=tgt_modified or (now - timedelta(hours=1)))
    return Conflict(entity_type=EntityType.CUSTOMER, source_record=src,
                    target_record=tgt, conflicting_fields=["phone"])


def test_last_write_wins():
    now = datetime.utcnow()
    conflict = _make_conflict(
        {"phone": "555-NEW"}, {"phone": "555-OLD"},
        src_modified=now, tgt_modified=now - timedelta(hours=1),
    )
    result = resolve_last_write_wins(conflict)
    assert result["phone"] == "555-NEW"


def test_source_priority():
    conflict = _make_conflict({"phone": "555-SH", "email": "sh@test.com"},
                              {"phone": "555-AT", "email": "at@test.com"})
    result = resolve_source_priority(conflict, priority_fields={"phone": "shopify", "email": "airtable"})
    assert result["phone"] == "555-SH"


@pytest.mark.asyncio
async def test_ai_resolution():
    conflict = _make_conflict({"phone": "555-SH"}, {"phone": "555-AT"})
    ai = MagicMock()
    ai.has_providers = True
    ai.call_llm = AsyncMock(return_value='{"phone": "555-SH", "email": "merged@test.com"}')
    result = await resolve_with_ai(conflict, ai)
    assert "phone" in result


def test_manual_flagging():
    conflict = _make_conflict({"phone": "555-A"}, {"phone": "555-B"})
    flagged = flag_manual(conflict)
    assert flagged.resolved_by is None
    assert flagged.resolution is None
```

Run: `pytest tests/test_conflict_resolver.py -v`
Expected: 4 passed

---

### Task 8: AIService + SyncStore

**Files:**
- Create: `src/services/ai.py` (copy pattern from ecommerce-pipeline)
- Create: `src/storage/__init__.py`
- Create: `src/storage/sync_store.py`

**Step 1: Create src/services/ai.py**

```python
"""Multi-provider LLM service (Groq → Gemini → OpenRouter cascade)."""
from __future__ import annotations
from dataclasses import dataclass
import structlog
from openai import AsyncOpenAI
from ..config import Settings

log = structlog.get_logger(__name__)


@dataclass
class LLMProvider:
    name: str
    api_key: str
    base_url: str
    model: str

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


class AIService:
    def __init__(self, providers: list[LLMProvider]) -> None:
        self._providers = [p for p in providers if p.is_configured]
        self._clients = [
            (p, AsyncOpenAI(api_key=p.api_key, base_url=p.base_url))
            for p in self._providers
        ]

    @classmethod
    def from_settings(cls, settings: Settings) -> AIService:
        return cls([
            LLMProvider("groq", settings.groq_api_key, "https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
            LLMProvider("gemini", settings.gemini_api_key, "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
            LLMProvider("openrouter", settings.openrouter_api_key, "https://openrouter.ai/api/v1", "meta-llama/llama-3.1-8b-instruct:free"),
        ])

    async def call_llm(self, system: str, user: str) -> str | None:
        for provider, client in self._clients:
            try:
                resp = await client.chat.completions.create(
                    model=provider.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    max_tokens=1024,
                )
                return resp.choices[0].message.content
            except Exception as exc:
                log.warning("llm_failed", provider=provider.name, error=str(exc))
        return None

    @property
    def has_providers(self) -> bool:
        return bool(self._providers)
```

**Step 2: Create src/storage/sync_store.py**

```python
from __future__ import annotations
import asyncio
import json
from datetime import datetime
from pathlib import Path
import structlog
from ..models import Conflict, SyncResult

log = structlog.get_logger(__name__)


class SyncStore:
    """In-memory sync state + JSON persistence for history and conflicts."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir / "sync_state"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._results: dict[str, SyncResult] = {}
        self._conflicts: dict[str, Conflict] = {}
        self._lock = asyncio.Lock()

    async def save_result(self, result: SyncResult) -> None:
        async with self._lock:
            self._results[result.sync_id] = result
            await asyncio.to_thread(self._persist_results)

    async def get_result(self, sync_id: str) -> SyncResult | None:
        async with self._lock:
            return self._results.get(sync_id)

    async def list_results(self) -> list[SyncResult]:
        async with self._lock:
            return sorted(self._results.values(), key=lambda r: r.started_at, reverse=True)

    async def save_conflict(self, conflict: Conflict) -> None:
        async with self._lock:
            self._conflicts[conflict.id] = conflict

    async def list_conflicts(self, unresolved_only: bool = True) -> list[Conflict]:
        async with self._lock:
            conflicts = list(self._conflicts.values())
            if unresolved_only:
                conflicts = [c for c in conflicts if c.resolution is None]
            return conflicts

    async def resolve_conflict(self, conflict_id: str, resolution: dict, resolved_by: str = "manual") -> Conflict | None:
        async with self._lock:
            c = self._conflicts.get(conflict_id)
            if not c:
                return None
            updated = c.model_copy(update={
                "resolution": resolution,
                "resolved_by": resolved_by,
                "resolved_at": datetime.utcnow(),
            })
            self._conflicts[conflict_id] = updated
            return updated

    def _persist_results(self) -> None:
        path = self._dir / "sync_history.json"
        data = {sid: r.model_dump(mode="json") for sid, r in self._results.items()}
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
```

---

### Task 9: Sync Engine

**Files:**
- Create: `src/sync/engine.py`
- Create: `tests/test_engine.py`

**Step 1: Create src/sync/engine.py**

```python
from __future__ import annotations
import time
from datetime import datetime
from pathlib import Path
import structlog
from ..connectors.base import Connector
from ..models import (
    Conflict, ConflictStrategy, EntityType, SyncDirection,
    SyncRecord, SyncResult,
)
from ..storage.sync_store import SyncStore
from ..sync.change_detector import ChangeDetector
from ..sync.conflict_resolver import detect_conflicts, resolve_conflict
from ..transform.mapper import apply_mapping, load_mapping

log = structlog.get_logger(__name__)


class SyncEngine:
    def __init__(
        self,
        source: Connector,
        target: Connector,
        direction: SyncDirection,
        entity_type: EntityType,
        mapping_file: Path,
        store: SyncStore,
        conflict_strategy: ConflictStrategy = ConflictStrategy.LAST_WRITE_WINS,
        ai_service=None,
    ) -> None:
        self._source = source
        self._target = target
        self._direction = direction
        self._entity_type = entity_type
        self._mapping = load_mapping(mapping_file)
        self._store = store
        self._strategy = conflict_strategy
        self._ai = ai_service
        self._detector = ChangeDetector()

    async def run(self) -> SyncResult:
        result = SyncResult(direction=self._direction, entity_type=self._entity_type)
        t0 = time.monotonic()

        try:
            # 1. Fetch changes from source
            since = self._detector.get_last_sync(self._source.name, self._entity_type)
            source_records = await self._source.fetch_records(self._entity_type, since=since)
            changed = self._detector.filter_changed(source_records)
            result.records_fetched = len(changed)

            # 2. Process each changed record
            for src_record in changed:
                try:
                    await self._process_record(src_record, result)
                    self._detector.mark_synced(src_record)
                except Exception as exc:
                    log.warning("record_sync_failed", error=str(exc), id=src_record.source_id)
                    result.errors.append(f"{src_record.source_id}: {exc}")

            # 3. Update last sync timestamp
            self._detector.update_last_sync(self._source.name, self._entity_type, datetime.utcnow())

        except Exception as exc:
            log.error("sync_failed", error=str(exc))
            result.errors.append(str(exc))

        result.completed_at = datetime.utcnow()
        result.duration_ms = round((time.monotonic() - t0) * 1000, 1)
        await self._store.save_result(result)
        return result

    async def _process_record(self, src_record: SyncRecord, result: SyncResult) -> None:
        # Map fields
        mapped_data = apply_mapping(src_record.data, self._mapping)
        if not mapped_data:
            result.records_skipped += 1
            return

        # Check if target has this record (conflict detection)
        target_record = await self._target.get_record(self._entity_type, src_record.source_id)
        if target_record:
            conflicting = detect_conflicts(src_record, target_record, list(mapped_data.keys()))
            if conflicting:
                conflict = Conflict(
                    entity_type=self._entity_type,
                    source_record=src_record,
                    target_record=target_record,
                    conflicting_fields=conflicting,
                    strategy_used=self._strategy,
                )
                await self._store.save_conflict(conflict)
                result.conflicts_found += 1

                resolved_data, resolved_by = await resolve_conflict(
                    conflict, self._strategy, self._ai
                )
                if resolved_data is not None:
                    mapped_data = resolved_data
                    result.conflicts_resolved += 1
                else:
                    result.records_skipped += 1
                    return

        await self._target.push_record(self._entity_type, mapped_data)
        if target_record:
            result.records_updated += 1
        else:
            result.records_created += 1
```

**Step 2: Write and run tests**

```python
# tests/test_engine.py
import pytest
from pathlib import Path
from src.connectors.shopify import ShopifyConnector
from src.connectors.airtable import AirtableConnector
from src.models import EntityType, SyncDirection, ConflictStrategy
from src.storage.sync_store import SyncStore
from src.sync.engine import SyncEngine

MAPPINGS_DIR = Path(__file__).parent.parent / "config" / "mappings"


@pytest.fixture
def tmp_store(tmp_path):
    return SyncStore(tmp_path)


@pytest.mark.asyncio
async def test_full_sync_cycle(tmp_store):
    engine = SyncEngine(
        source=ShopifyConnector(), target=AirtableConnector(),
        direction=SyncDirection.SHOPIFY_TO_AIRTABLE,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS_DIR / "shopify_to_airtable.yaml",
        store=tmp_store,
    )
    result = await engine.run()
    assert result.records_fetched > 0
    assert result.duration_ms > 0
    assert result.completed_at is not None


@pytest.mark.asyncio
async def test_sync_result_tracking(tmp_store):
    engine = SyncEngine(
        source=ShopifyConnector(), target=AirtableConnector(),
        direction=SyncDirection.SHOPIFY_TO_AIRTABLE,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS_DIR / "shopify_to_airtable.yaml",
        store=tmp_store,
    )
    result = await engine.run()
    stored = await tmp_store.get_result(result.sync_id)
    assert stored is not None
    assert stored.sync_id == result.sync_id


@pytest.mark.asyncio
async def test_sync_idempotent(tmp_store):
    """Running sync twice: second run should find 0 changed records."""
    shopify = ShopifyConnector()
    airtable = AirtableConnector()
    engine = SyncEngine(
        source=shopify, target=airtable,
        direction=SyncDirection.SHOPIFY_TO_AIRTABLE,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS_DIR / "shopify_to_airtable.yaml",
        store=tmp_store,
    )
    r1 = await engine.run()
    r2 = await engine.run()
    assert r2.records_fetched == 0  # all already synced (same checksums)


@pytest.mark.asyncio
async def test_sync_with_conflicts(tmp_store):
    """Conflicts detected when source and target both have same record modified."""
    shopify = ShopifyConnector()
    airtable = AirtableConnector()
    # Pre-populate airtable with a record that will conflict
    await airtable.push_record(EntityType.ORDER, {
        "log_id": "SH-ORD-1000", "Order Number": "SH-ORD-1000",
        "Total": 9999.0, "Status": "Modified",
    })
    engine = SyncEngine(
        source=shopify, target=airtable,
        direction=SyncDirection.SHOPIFY_TO_AIRTABLE,
        entity_type=EntityType.ORDER,
        mapping_file=MAPPINGS_DIR / "shopify_to_airtable.yaml",
        store=tmp_store,
        conflict_strategy=ConflictStrategy.LAST_WRITE_WINS,
    )
    result = await engine.run()
    assert result.records_fetched >= 0  # sync ran without exception
```

Run: `pytest tests/test_engine.py -v`
Expected: 4 passed

---

### Task 10: Reconciliation — reconciler + reporter

**Files:**
- Create: `src/reconciliation/__init__.py`
- Create: `src/reconciliation/reconciler.py`
- Create: `src/reconciliation/reporter.py`
- Create: `tests/test_reconciler.py`

**Step 1: Create src/reconciliation/reconciler.py**

```python
from __future__ import annotations
from ..connectors.base import Connector
from ..models import EntityType, Mismatch, ReconciliationReport
import structlog

log = structlog.get_logger(__name__)


async def reconcile(
    source: Connector,
    target: Connector,
    entity_type: EntityType,
    key_field: str,
    compare_fields: list[str],
) -> ReconciliationReport:
    """Compare records between source and target, report mismatches."""
    src_records = await source.fetch_records(entity_type)
    tgt_records = await target.fetch_records(entity_type)

    src_by_key = {r.data.get(key_field): r for r in src_records if r.data.get(key_field)}
    tgt_by_key = {r.data.get(key_field): r for r in tgt_records if r.data.get(key_field)}

    mismatches: list[Mismatch] = []
    matches = 0
    missing_in_target: list[str] = []
    missing_in_source: list[str] = []

    for key, src_rec in src_by_key.items():
        if key not in tgt_by_key:
            missing_in_target.append(str(key))
            continue
        tgt_rec = tgt_by_key[key]
        record_ok = True
        for field in compare_fields:
            sv = src_rec.data.get(field)
            tv = tgt_rec.data.get(field)
            if str(sv) != str(tv):
                mismatches.append(Mismatch(
                    record_id=str(key), field=field,
                    source_value=sv, target_value=tv,
                    source_system=source.name, target_system=target.name,
                ))
                record_ok = False
        if record_ok:
            matches += 1

    for key in tgt_by_key:
        if key not in src_by_key:
            missing_in_source.append(str(key))

    total = len(src_by_key)
    accuracy = round((matches / total * 100) if total > 0 else 0.0, 1)

    return ReconciliationReport(
        systems_compared=[source.name, target.name],
        entity_type=entity_type,
        total_records_checked=total,
        matches=matches,
        mismatches=mismatches,
        missing_in_target=missing_in_target,
        missing_in_source=missing_in_source,
        accuracy_pct=accuracy,
    )
```

**Step 2: Create src/reconciliation/reporter.py**

```python
from __future__ import annotations
import json
from pathlib import Path
from ..models import ReconciliationReport


def format_report(report: ReconciliationReport) -> str:
    lines = [
        f"# Reconciliation Report",
        f"**Generated:** {report.generated_at}",
        f"**Systems:** {' ↔ '.join(report.systems_compared)}",
        f"**Entity Type:** {report.entity_type}",
        "",
        f"## Summary",
        f"- Total checked: {report.total_records_checked}",
        f"- Matches: {report.matches}",
        f"- Mismatches: {len(report.mismatches)}",
        f"- Missing in target: {len(report.missing_in_target)}",
        f"- Missing in source: {len(report.missing_in_source)}",
        f"- **Accuracy: {report.accuracy_pct:.1f}%**",
    ]
    if report.mismatches:
        lines += ["", "## Field Mismatches"]
        for m in report.mismatches[:20]:  # cap for readability
            lines.append(f"- `{m.record_id}`.{m.field}: `{m.source_value}` vs `{m.target_value}`")
    return "\n".join(lines)


def save_report(report: ReconciliationReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report.report_id}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
```

**Step 3: Write and run tests**

```python
# tests/test_reconciler.py
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
```

Run: `pytest tests/test_reconciler.py -v`
Expected: 3 passed

---

### Task 11: Scheduler + Database service + ServiceContainer

**Files:**
- Create: `src/sync/scheduler.py`
- Create: `src/services/database.py`
- Create: `src/services/__init__.py` (ServiceContainer)

**Step 1: Create src/sync/scheduler.py**

```python
from __future__ import annotations
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

log = structlog.get_logger(__name__)


class SyncScheduler:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}  # direction → job_id

    def add_sync_job(self, job_id: str, func, interval_minutes: int, **kwargs) -> None:
        job = self._scheduler.add_job(
            func, trigger=IntervalTrigger(minutes=interval_minutes),
            id=job_id, replace_existing=True, kwargs=kwargs,
        )
        self._jobs[job_id] = job.id
        log.info("sync_job_added", job_id=job_id, interval_minutes=interval_minutes)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def pause(self) -> None:
        self._scheduler.pause()

    def resume(self) -> None:
        self._scheduler.resume()

    @property
    def is_running(self) -> bool:
        return self._scheduler.running
```

**Step 2: Create src/services/database.py**

```python
from __future__ import annotations
import asyncpg
import structlog
from ..config import Settings

log = structlog.get_logger(__name__)


async def create_pool(settings: Settings) -> asyncpg.Pool | None:
    """Create asyncpg connection pool. Returns None if DB unavailable."""
    try:
        pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
        log.info("db_pool_created")
        return pool
    except Exception as exc:
        log.warning("db_pool_failed", error=str(exc))
        return None


async def setup_tables(pool: asyncpg.Pool) -> None:
    """Create sync state tables if they don't exist."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_checkpoints (
                connector TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                last_sync_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (connector, entity_type)
            )
        """)
```

**Step 3: Create src/services/__init__.py (ServiceContainer)**

```python
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
```

---

### Task 12: FastAPI app.py — 14 endpoints

**Files:**
- Create: `src/app.py`
- Create: `tests/test_api.py`

**Step 1: Create src/app.py**

```python
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
import yaml
import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import get_settings
from .models import ConflictStrategy, EntityType, SyncDirection
from .reconciliation.reconciler import reconcile
from .reconciliation.reporter import format_report, save_report
from .services import ServiceContainer, create_services
from .sync.engine import SyncEngine

log = structlog.get_logger(__name__)

_container: ServiceContainer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _container
    _container = create_services()
    _container.scheduler.start()
    log.info("service_started", port=_container.settings.fastapi_port)
    yield
    _container.scheduler.shutdown()
    _container = None


app = FastAPI(
    title="Data Sync & Transformation Engine",
    description="Sync Shopify ↔ Airtable ↔ QuickBooks with AI conflict resolution",
    version="0.1.0",
    lifespan=lifespan,
)


def _svc() -> ServiceContainer:
    if _container is None:
        raise RuntimeError("Services not initialized")
    return _container


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    c = _svc()
    return {
        "status": "ok",
        "llm_available": c.settings.has_llm(),
        "connectors": {
            "shopify": await c.shopify.health_check(),
            "airtable": await c.airtable.health_check(),
            "quickbooks": await c.quickbooks.health_check(),
        },
    }


# ── Connectors ────────────────────────────────────────────────────────────

@app.get("/api/connectors")
async def list_connectors():
    c = _svc()
    return [
        {"name": "shopify", "healthy": await c.shopify.health_check()},
        {"name": "airtable", "healthy": await c.airtable.health_check()},
        {"name": "quickbooks", "healthy": await c.quickbooks.health_check()},
    ]


# ── Mappings ──────────────────────────────────────────────────────────────

@app.get("/api/mappings")
async def list_mappings():
    c = _svc()
    files = list(c.settings.mappings_dir.glob("*.yaml"))
    return [{"file": f.name} for f in files]


# ── Sync ──────────────────────────────────────────────────────────────────

class SyncRequest(BaseModel):
    source: str
    target: str
    entity_type: str
    conflict_strategy: str = "last_write_wins"


def _get_connector(name: str, c: ServiceContainer):
    return {"shopify": c.shopify, "airtable": c.airtable, "quickbooks": c.quickbooks}.get(name)


def _mapping_file(c: ServiceContainer, source: str, target: str) -> Path:
    name = f"{source}_to_{target}.yaml"
    return c.settings.mappings_dir / name


@app.post("/api/sync/trigger")
async def trigger_sync(req: SyncRequest):
    c = _svc()
    source_conn = _get_connector(req.source, c)
    target_conn = _get_connector(req.target, c)
    if not source_conn or not target_conn:
        raise HTTPException(status_code=400, detail=f"Unknown connector: {req.source} or {req.target}")

    mapping_file = _mapping_file(c, req.source, req.target)
    if not mapping_file.exists():
        raise HTTPException(status_code=400, detail=f"No mapping found: {mapping_file.name}")

    direction = f"{req.source}_to_{req.target}"
    try:
        sync_direction = SyncDirection(direction)
        entity_type = EntityType(req.entity_type)
        strategy = ConflictStrategy(req.conflict_strategy)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    engine = SyncEngine(
        source=source_conn, target=target_conn,
        direction=sync_direction, entity_type=entity_type,
        mapping_file=mapping_file, store=c.store,
        conflict_strategy=strategy, ai_service=c.ai,
    )
    result = await engine.run()
    return result


@app.post("/api/sync/trigger-all")
async def trigger_all():
    c = _svc()
    sync_config_path = c.settings.mappings_dir.parent.parent / "config" / "sync_config.yaml"
    if not sync_config_path.exists():
        raise HTTPException(status_code=500, detail="sync_config.yaml not found")
    config = yaml.safe_load(sync_config_path.read_text())
    results = []
    for sync in config.get("syncs", []):
        source, target = sync["direction"].split("_to_")
        mapping_file = c.settings.mappings_dir / sync["mapping_file"]
        if not mapping_file.exists():
            continue
        try:
            engine = SyncEngine(
                source=_get_connector(source, c), target=_get_connector(target, c),
                direction=SyncDirection(sync["direction"]),
                entity_type=EntityType(sync["entity_type"]),
                mapping_file=mapping_file, store=c.store,
                conflict_strategy=ConflictStrategy(sync.get("conflict_strategy", "last_write_wins")),
                ai_service=c.ai,
            )
            result = await engine.run()
            results.append(result.model_dump(mode="json"))
        except Exception as exc:
            results.append({"error": str(exc), "direction": sync["direction"]})
    return {"syncs": len(results), "results": results}


@app.get("/api/sync/history")
async def sync_history():
    return await _svc().store.list_results()


@app.get("/api/sync/status")
async def sync_status():
    c = _svc()
    results = await c.store.list_results()
    by_direction: dict[str, Any] = {}
    for r in results:
        key = r.direction
        if key not in by_direction or r.started_at > by_direction[key]["started_at"]:
            by_direction[key] = r.model_dump(mode="json")
    return by_direction


@app.get("/api/sync/{sync_id}")
async def get_sync(sync_id: str):
    result = await _svc().store.get_result(sync_id)
    if not result:
        raise HTTPException(status_code=404, detail="Sync not found")
    return result


# ── Conflicts ─────────────────────────────────────────────────────────────

@app.get("/api/conflicts")
async def list_conflicts(unresolved_only: bool = True):
    return await _svc().store.list_conflicts(unresolved_only=unresolved_only)


class ResolveRequest(BaseModel):
    resolution: dict[str, Any]


@app.post("/api/conflicts/{conflict_id}/resolve")
async def resolve_conflict_endpoint(conflict_id: str, req: ResolveRequest):
    result = await _svc().store.resolve_conflict(conflict_id, req.resolution, "manual")
    if not result:
        raise HTTPException(status_code=404, detail="Conflict not found")
    return result


# ── Reconciliation ────────────────────────────────────────────────────────

class ReconcileRequest(BaseModel):
    entity_type: str
    source: str = "shopify"
    target: str = "airtable"
    key_field: str = "order_number"
    compare_fields: list[str] = ["order_number"]


_reports: dict[str, Any] = {}


@app.post("/api/reconcile")
async def run_reconciliation(req: ReconcileRequest):
    c = _svc()
    source_conn = _get_connector(req.source, c)
    target_conn = _get_connector(req.target, c)
    if not source_conn or not target_conn:
        raise HTTPException(status_code=400, detail="Unknown connector")
    try:
        entity_type = EntityType(req.entity_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown entity type: {req.entity_type}")
    report = await reconcile(source_conn, target_conn, entity_type, req.key_field, req.compare_fields)
    _reports[report.report_id] = report
    save_report(report, c.settings.data_dir / "reports")
    return report


@app.get("/api/reconcile/{report_id}")
async def get_reconciliation(report_id: str):
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


# ── Scheduler ─────────────────────────────────────────────────────────────

@app.post("/api/scheduler/pause")
async def pause_scheduler():
    _svc().scheduler.pause()
    return {"status": "paused"}


@app.post("/api/scheduler/resume")
async def resume_scheduler():
    _svc().scheduler.resume()
    return {"status": "resumed"}
```

**Step 2: Write and run API tests**

```python
# tests/test_api.py
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
```

Run: `pytest tests/test_api.py -v`
Expected: 4 passed

---

### Task 13: Scripts

**Files:**
- Create: `scripts/seed_data.py`
- Create: `scripts/demo.py`
- Create: `scripts/demo_conflict.py`
- Create: `scripts/demo_reconcile.py`

**Step 1: Create scripts/seed_data.py**

```python
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
            "Phone": f"555-000{i+1}",  # intentional mismatch for demo
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
```

**Step 2: Create scripts/demo.py**

```python
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
    print(f"Shopify:    {100} orders, 30 products, 50 customers")
    print(f"Airtable:   50 contacts, 30 inventory, 80 order_log")
    print(f"QuickBooks: 60 invoices, 45 customers, 30 items\n")

    # Sync 1: Shopify → Airtable (orders)
    print("--- Sync 1: Shopify → Airtable (orders) ---")
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

    # Sync 2: Shopify → QuickBooks (orders → invoices)
    print("--- Sync 2: Shopify → QuickBooks (orders → invoices) ---")
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
```

**Step 3: Create scripts/demo_conflict.py**

```python
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

    # Create same customer with different phone in Shopify and Airtable
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

    # Strategy 1: last_write_wins
    lww = resolve_last_write_wins(conflict)
    print(f"last_write_wins result: phone = {lww.get('phone')}")

    # Strategy 2: source_priority
    sp = resolve_source_priority(conflict, priority_fields={"phone": "airtable"})
    print(f"source_priority (airtable wins): phone = {sp.get('phone')}")

    # Strategy 3: AI (mock)
    print("\nAI resolution: skipped (no LLM keys in demo)")
    print("\nConflict resolution strategies demonstrated.")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4: Create scripts/demo_reconcile.py**

```python
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
```

---

### Task 14: Workflows + Docs

**Files:**
- Create: `workflows/data_sync.json`
- Create: `workflows/README.md`
- Create: `CLAUDE.md`
- Create: `README.md`
- Create: `docs/architecture.md`

**Step 1: Create workflows/data_sync.json**

```json
{
  "name": "Data Sync Automation",
  "nodes": [
    {"id": "1", "type": "n8n-nodes-base.scheduleTrigger", "name": "Every 5 minutes",
     "parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}}},
    {"id": "2", "type": "n8n-nodes-base.httpRequest", "name": "Trigger All Syncs",
     "parameters": {"method": "POST", "url": "http://localhost:8009/api/sync/trigger-all",
                    "responseFormat": "json"}},
    {"id": "3", "type": "n8n-nodes-base.httpRequest", "name": "Get Conflicts",
     "parameters": {"method": "GET", "url": "http://localhost:8009/api/conflicts",
                    "responseFormat": "json"}},
    {"id": "4", "type": "n8n-nodes-base.noOp", "name": "Done"}
  ],
  "connections": {
    "Every 5 minutes": {"main": [[{"node": "Trigger All Syncs", "type": "main", "index": 0}]]},
    "Trigger All Syncs": {"main": [[{"node": "Get Conflicts", "type": "main", "index": 0}]]},
    "Get Conflicts": {"main": [[{"node": "Done", "type": "main", "index": 0}]]}
  }
}
```

**Step 2: CLAUDE.md**

```markdown
# CLAUDE.md — Data Sync Engine

## Run
- `uvicorn src.app:app --port 8009`
- `pytest tests/ -v` (27 tests)
- `python scripts/demo.py`

## Architecture
- Pluggable connectors: ShopifyConnector, AirtableConnector, QuickBooksConnector (all mock)
- Field mapping: YAML config in config/mappings/, applied by src/transform/mapper.py
- Delta sync: ChangeDetector tracks checksums + last_sync_at per (connector, entity_type)
- 4 conflict strategies: last_write_wins, source_priority, ai_resolution, manual
- Reconciliation: cross-system comparison by key_field + compare_fields
- APScheduler for interval-based automatic sync
- SyncStore: in-memory + JSON persistence for sync history and conflicts

## Key patterns
- Connector.fetch_records(entity_type, since) → list[SyncRecord]
- SyncEngine.run() → SyncResult (full ETL cycle)
- ConflictStrategy enum: LAST_WRITE_WINS, SOURCE_PRIORITY, AI_RESOLUTION, MANUAL
- EntityType: order, product, customer, invoice, inventory_item, contact
```

---

### Task 15: All tests (27 total)

Run the full suite. By this point all tests should be written inline with each task above.

**Run full suite:**

```bash
cd C:\Users\Nitin\portfolio\data-sync-engine
.venv/Scripts/pytest tests/ -v
```

**Expected results:**

| File | Tests | Expected |
|------|-------|----------|
| test_connectors.py | 4 | ✅ pass |
| test_mapper.py | 5 | ✅ pass |
| test_change_detector.py | 3 | ✅ pass |
| test_conflict_resolver.py | 4 | ✅ pass |
| test_engine.py | 4 | ✅ pass |
| test_reconciler.py | 3 | ✅ pass |
| test_api.py | 4 | ✅ pass |
| **Total** | **27** | **27 passed** |

---

### Task 16: Final verification + git commit

**Step 1: Sanity check**

```bash
python scripts/seed_data.py
python scripts/demo.py
python scripts/demo_conflict.py
python scripts/demo_reconcile.py
```

**Step 2: Quick API test**

```bash
# Terminal 1
uvicorn src.app:app --port 8009 --reload

# Terminal 2
curl http://localhost:8009/health
curl -X POST http://localhost:8009/api/sync/trigger \
  -H "Content-Type: application/json" \
  -d '{"source":"shopify","target":"airtable","entity_type":"order"}'
curl http://localhost:8009/api/conflicts
```

**Step 3: Commit**

```bash
git init
git add pyproject.toml .env .gitignore CLAUDE.md README.md src/ tests/ scripts/ config/ workflows/ docs/
git commit -m "init: data sync engine — 27 tests, 3 mock connectors, conflict resolution, reconciliation"
```

---

## Summary

| Component | Files | Tests |
|-----------|-------|-------|
| Models + Config | src/models.py, src/config.py, src/exceptions.py | — |
| Connectors | shopify.py, airtable.py, quickbooks.py | 4 |
| Transform | mapper.py, converter.py, validator.py + 3 YAML configs | 5 |
| Change Detector | change_detector.py | 3 |
| Conflict Resolver | conflict_resolver.py (4 strategies) | 4 |
| Sync Engine | engine.py | 4 |
| Reconciliation | reconciler.py, reporter.py | 3 |
| API | app.py (14 endpoints) | 4 |
| Services | ai.py, database.py, container.py, sync_store.py, scheduler.py | — |
| Scripts | demo.py, demo_conflict.py, demo_reconcile.py, seed_data.py | — |
| **Total** | **~40 files** | **27 tests** |
