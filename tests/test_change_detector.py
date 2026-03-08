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
