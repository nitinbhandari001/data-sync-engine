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
