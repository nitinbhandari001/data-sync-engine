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
