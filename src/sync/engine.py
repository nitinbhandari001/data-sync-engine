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
