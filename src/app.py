from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
import yaml
import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import get_settings
from .models import ConflictStrategy, EntityType, SyncDirection
from .reconciliation.reconciler import reconcile
from .reconciliation.reporter import format_report, save_report
from .services import ServiceContainer, create_services
from .sync.engine import SyncEngine

log = structlog.get_logger(__name__)

_container: ServiceContainer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _container
    _container = create_services()
    _container.scheduler.start()
    log.info("service_started", port=_container.settings.fastapi_port)
    yield
    _container.scheduler.shutdown()
    _container = None


app = FastAPI(
    title="Data Sync & Transformation Engine",
    description="Sync Shopify ↔ Airtable ↔ QuickBooks with AI conflict resolution",
    version="0.1.0",
    lifespan=lifespan,
)


def _svc() -> ServiceContainer:
    if _container is None:
        raise RuntimeError("Services not initialized")
    return _container


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    c = _svc()
    return {
        "status": "ok",
        "llm_available": c.settings.has_llm(),
        "connectors": {
            "shopify": await c.shopify.health_check(),
            "airtable": await c.airtable.health_check(),
            "quickbooks": await c.quickbooks.health_check(),
        },
    }


# ── Connectors ────────────────────────────────────────────────────────────

@app.get("/api/connectors")
async def list_connectors():
    c = _svc()
    return [
        {"name": "shopify", "healthy": await c.shopify.health_check()},
        {"name": "airtable", "healthy": await c.airtable.health_check()},
        {"name": "quickbooks", "healthy": await c.quickbooks.health_check()},
    ]


# ── Mappings ──────────────────────────────────────────────────────────────

@app.get("/api/mappings")
async def list_mappings():
    c = _svc()
    files = list(c.settings.mappings_dir.glob("*.yaml"))
    return [{"file": f.name} for f in files]


# ── Sync ──────────────────────────────────────────────────────────────────

class SyncRequest(BaseModel):
    source: str
    target: str
    entity_type: str
    conflict_strategy: str = "last_write_wins"


def _get_connector(name: str, c: ServiceContainer):
    return {"shopify": c.shopify, "airtable": c.airtable, "quickbooks": c.quickbooks}.get(name)


def _mapping_file(c: ServiceContainer, source: str, target: str) -> Path:
    name = f"{source}_to_{target}.yaml"
    return c.settings.mappings_dir / name


@app.post("/api/sync/trigger")
async def trigger_sync(req: SyncRequest):
    c = _svc()
    source_conn = _get_connector(req.source, c)
    target_conn = _get_connector(req.target, c)
    if not source_conn or not target_conn:
        raise HTTPException(status_code=400, detail=f"Unknown connector: {req.source} or {req.target}")

    mapping_file = _mapping_file(c, req.source, req.target)
    if not mapping_file.exists():
        raise HTTPException(status_code=400, detail=f"No mapping found: {mapping_file.name}")

    direction = f"{req.source}_to_{req.target}"
    try:
        sync_direction = SyncDirection(direction)
        entity_type = EntityType(req.entity_type)
        strategy = ConflictStrategy(req.conflict_strategy)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    engine = SyncEngine(
        source=source_conn, target=target_conn,
        direction=sync_direction, entity_type=entity_type,
        mapping_file=mapping_file, store=c.store,
        conflict_strategy=strategy, ai_service=c.ai,
    )
    result = await engine.run()
    return result


@app.post("/api/sync/trigger-all")
async def trigger_all():
    c = _svc()
    sync_config_path = c.settings.mappings_dir.parent / "sync_config.yaml"
    if not sync_config_path.exists():
        raise HTTPException(status_code=500, detail="sync_config.yaml not found")
    config = yaml.safe_load(sync_config_path.read_text())
    results = []
    for sync in config.get("syncs", []):
        source, target = sync["direction"].split("_to_")
        mapping_file = c.settings.mappings_dir / sync["mapping_file"]
        if not mapping_file.exists():
            continue
        try:
            engine = SyncEngine(
                source=_get_connector(source, c), target=_get_connector(target, c),
                direction=SyncDirection(sync["direction"]),
                entity_type=EntityType(sync["entity_type"]),
                mapping_file=mapping_file, store=c.store,
                conflict_strategy=ConflictStrategy(sync.get("conflict_strategy", "last_write_wins")),
                ai_service=c.ai,
            )
            result = await engine.run()
            results.append(result.model_dump(mode="json"))
        except Exception as exc:
            results.append({"error": str(exc), "direction": sync["direction"]})
    return {"syncs": len(results), "results": results}


@app.get("/api/sync/history")
async def sync_history():
    return await _svc().store.list_results()


@app.get("/api/sync/status")
async def sync_status():
    c = _svc()
    results = await c.store.list_results()
    by_direction: dict[str, Any] = {}
    for r in results:
        key = r.direction
        if key not in by_direction or r.started_at > by_direction[key]["started_at"]:
            by_direction[key] = r.model_dump(mode="json")
    return by_direction


@app.get("/api/sync/{sync_id}")
async def get_sync(sync_id: str):
    result = await _svc().store.get_result(sync_id)
    if not result:
        raise HTTPException(status_code=404, detail="Sync not found")
    return result


# ── Conflicts ─────────────────────────────────────────────────────────────

@app.get("/api/conflicts")
async def list_conflicts(unresolved_only: bool = True):
    return await _svc().store.list_conflicts(unresolved_only=unresolved_only)


class ResolveRequest(BaseModel):
    resolution: dict[str, Any]


@app.post("/api/conflicts/{conflict_id}/resolve")
async def resolve_conflict_endpoint(conflict_id: str, req: ResolveRequest):
    result = await _svc().store.resolve_conflict(conflict_id, req.resolution, "manual")
    if not result:
        raise HTTPException(status_code=404, detail="Conflict not found")
    return result


# ── Reconciliation ────────────────────────────────────────────────────────

class ReconcileRequest(BaseModel):
    entity_type: str
    source: str = "shopify"
    target: str = "airtable"
    key_field: str = "order_number"
    compare_fields: list[str] = ["order_number"]


_reports: dict[str, Any] = {}


@app.post("/api/reconcile")
async def run_reconciliation(req: ReconcileRequest):
    c = _svc()
    source_conn = _get_connector(req.source, c)
    target_conn = _get_connector(req.target, c)
    if not source_conn or not target_conn:
        raise HTTPException(status_code=400, detail="Unknown connector")
    try:
        entity_type = EntityType(req.entity_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown entity type: {req.entity_type}")
    report = await reconcile(source_conn, target_conn, entity_type, req.key_field, req.compare_fields)
    _reports[report.report_id] = report
    save_report(report, c.settings.data_dir / "reports")
    return report


@app.get("/api/reconcile/{report_id}")
async def get_reconciliation(report_id: str):
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


# ── Scheduler ─────────────────────────────────────────────────────────────

@app.post("/api/scheduler/pause")
async def pause_scheduler():
    _svc().scheduler.pause()
    return {"status": "paused"}


@app.post("/api/scheduler/resume")
async def resume_scheduler():
    _svc().scheduler.resume()
    return {"status": "resumed"}
