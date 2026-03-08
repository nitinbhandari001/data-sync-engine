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
