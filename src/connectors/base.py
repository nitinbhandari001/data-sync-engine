from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime
from ..models import EntityType, SyncRecord


class Connector(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch_records(
        self, entity_type: EntityType, since: datetime | None = None
    ) -> list[SyncRecord]: ...

    @abstractmethod
    async def push_record(self, entity_type: EntityType, data: dict) -> str: ...

    @abstractmethod
    async def get_record(
        self, entity_type: EntityType, record_id: str
    ) -> SyncRecord | None: ...

    @abstractmethod
    async def get_schema(self, entity_type: EntityType) -> dict: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
