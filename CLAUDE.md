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
