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
