from __future__ import annotations
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

log = structlog.get_logger(__name__)


class SyncScheduler:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}  # direction → job_id

    def add_sync_job(self, job_id: str, func, interval_minutes: int, **kwargs) -> None:
        job = self._scheduler.add_job(
            func, trigger=IntervalTrigger(minutes=interval_minutes),
            id=job_id, replace_existing=True, kwargs=kwargs,
        )
        self._jobs[job_id] = job.id
        log.info("sync_job_added", job_id=job_id, interval_minutes=interval_minutes)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def pause(self) -> None:
        self._scheduler.pause()

    def resume(self) -> None:
        self._scheduler.resume()

    @property
    def is_running(self) -> bool:
        return self._scheduler.running
