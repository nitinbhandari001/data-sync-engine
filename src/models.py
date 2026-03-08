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
