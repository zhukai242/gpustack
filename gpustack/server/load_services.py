from typing import List
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import select

from gpustack.schemas.load import (
    WorkerLoad,
    WorkerLoadCreate,
    GPULoad,
    GPULoadCreate,
    WorkerLog,
    WorkerLogCreate,
    GPULog,
    GPULogCreate,
)


class WorkerLoadService:
    """Service for managing worker load data."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, worker_load: WorkerLoadCreate) -> WorkerLoad:
        """Create a new worker load record."""
        db_worker_load = WorkerLoad(**worker_load.model_dump())
        self._session.add(db_worker_load)
        await self._session.flush()
        return db_worker_load

    async def create_many(
        self, worker_loads: List[WorkerLoadCreate]
    ) -> List[WorkerLoad]:
        """Create multiple worker load records."""
        db_worker_loads = [WorkerLoad(**wl.model_dump()) for wl in worker_loads]
        self._session.add_all(db_worker_loads)
        await self._session.flush()
        return db_worker_loads

    async def get_by_worker_id(
        self, worker_id: int, limit: int = 100
    ) -> List[WorkerLoad]:
        """Get worker load records by worker ID."""
        statement = (
            select(WorkerLoad)
            .where(WorkerLoad.worker_id == worker_id)
            .order_by(WorkerLoad.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()


class GPULoadService:
    """Service for managing GPU load data."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, gpu_load: GPULoadCreate) -> GPULoad:
        """Create a new GPU load record."""
        db_gpu_load = GPULoad(**gpu_load.model_dump())
        self._session.add(db_gpu_load)
        await self._session.flush()
        return db_gpu_load

    async def create_many(self, gpu_loads: List[GPULoadCreate]) -> List[GPULoad]:
        """Create multiple GPU load records."""
        db_gpu_loads = [GPULoad(**gl.model_dump()) for gl in gpu_loads]
        self._session.add_all(db_gpu_loads)
        await self._session.flush()
        return db_gpu_loads

    async def get_by_worker_id(self, worker_id: int, limit: int = 100) -> List[GPULoad]:
        """Get GPU load records by worker ID."""
        statement = (
            select(GPULoad)
            .where(GPULoad.worker_id == worker_id)
            .order_by(GPULoad.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def get_by_gpu_index(
        self, worker_id: int, gpu_index: int, limit: int = 100
    ) -> List[GPULoad]:
        """Get GPU load records by worker ID and GPU index."""
        statement = (
            select(GPULoad)
            .where(GPULoad.worker_id == worker_id, GPULoad.gpu_index == gpu_index)
            .order_by(GPULoad.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def get_by_gpu_id(self, gpu_id: str, limit: int = 100) -> List[GPULoad]:
        """Get GPU load records by GPU ID."""
        statement = (
            select(GPULoad)
            .where(GPULoad.gpu_id == gpu_id)
            .order_by(GPULoad.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()


class WorkerLogService:
    """Service for managing worker log data."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, worker_log: WorkerLogCreate) -> WorkerLog:
        """Create a new worker log record."""
        db_worker_log = WorkerLog(**worker_log.model_dump())
        self._session.add(db_worker_log)
        await self._session.flush()
        return db_worker_log

    async def create_many(self, worker_logs: List[WorkerLogCreate]) -> List[WorkerLog]:
        """Create multiple worker log records."""
        db_worker_logs = [WorkerLog(**wl.model_dump()) for wl in worker_logs]
        self._session.add_all(db_worker_logs)
        await self._session.flush()
        return db_worker_logs

    async def get_by_worker_id(
        self, worker_id: int, limit: int = 100
    ) -> List[WorkerLog]:
        """Get worker log records by worker ID."""
        statement = (
            select(WorkerLog)
            .where(WorkerLog.worker_id == worker_id)
            .order_by(WorkerLog.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()


class GPULogService:
    """Service for managing GPU log data."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, gpu_log: GPULogCreate) -> GPULog:
        """Create a new GPU log record."""
        db_gpu_log = GPULog(**gpu_log.model_dump())
        self._session.add(db_gpu_log)
        await self._session.flush()
        return db_gpu_log

    async def create_many(self, gpu_logs: List[GPULogCreate]) -> List[GPULog]:
        """Create multiple GPU log records."""
        db_gpu_logs = [GPULog(**gl.model_dump()) for gl in gpu_logs]
        self._session.add_all(db_gpu_logs)
        await self._session.flush()
        return db_gpu_logs

    async def get_by_worker_id(self, worker_id: int, limit: int = 100) -> List[GPULog]:
        """Get GPU log records by worker ID."""
        statement = (
            select(GPULog)
            .where(GPULog.worker_id == worker_id)
            .order_by(GPULog.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def get_by_gpu_id(self, gpu_id: str, limit: int = 100) -> List[GPULog]:
        """Get GPU log records by GPU ID."""
        statement = (
            select(GPULog)
            .where(GPULog.gpu_id == gpu_id)
            .order_by(GPULog.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def get_by_gpu_index(
        self, worker_id: int, gpu_index: int, limit: int = 100
    ) -> List[GPULog]:
        """Get GPU log records by worker ID and GPU index."""
        statement = (
            select(GPULog)
            .where(GPULog.worker_id == worker_id, GPULog.gpu_index == gpu_index)
            .order_by(GPULog.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()
