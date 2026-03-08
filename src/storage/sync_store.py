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
