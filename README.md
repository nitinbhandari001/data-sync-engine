# Data Sync & Transformation Engine

FastAPI service that keeps Shopify, Airtable, and QuickBooks data synchronized via pluggable connectors, field mapping, delta sync, conflict resolution, and reconciliation reporting — all in mock mode (zero API keys).

## Features
- **3 mock connectors**: Shopify (100 orders/30 products/50 customers), Airtable (50 contacts/30 inventory/80 order_log), QuickBooks (60 invoices/45 customers/30 items)
- **Field mapping engine**: YAML-configured transforms (rename, convert, value_map, concat)
- **Delta sync**: Checksum-based change detection — only syncs modified records
- **4 conflict strategies**: last_write_wins, source_priority, ai_resolution, manual
- **Reconciliation**: Cross-system consistency checks with accuracy reporting
- **APScheduler**: Interval-based automatic sync jobs
- **27 tests passing**

## Quick Start

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# Demo (no credentials needed)
python scripts/demo.py
python scripts/demo_conflict.py
python scripts/demo_reconcile.py

# API
uvicorn src.app:app --port 8009
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | System health + connector status |
| GET | /api/connectors | List connectors |
| GET | /api/mappings | List YAML mapping files |
| POST | /api/sync/trigger | Trigger single sync |
| POST | /api/sync/trigger-all | Trigger all configured syncs |
| GET | /api/sync/history | Sync run history |
| GET | /api/sync/status | Latest status per direction |
| GET | /api/sync/{sync_id} | Get specific sync result |
| GET | /api/conflicts | List unresolved conflicts |
| POST | /api/conflicts/{id}/resolve | Manually resolve a conflict |
| POST | /api/reconcile | Run reconciliation report |
| GET | /api/reconcile/{report_id} | Get reconciliation report |
| POST | /api/scheduler/pause | Pause scheduler |
| POST | /api/scheduler/resume | Resume scheduler |

## Port: 8009
