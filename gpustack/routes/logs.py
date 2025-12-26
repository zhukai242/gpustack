from typing import List, Optional
from fastapi import APIRouter, Query
from sqlalchemy import select
from gpustack.server.deps import SessionDep, CurrentUserDep
from gpustack.schemas.load import WorkerLog, GPULog
from gpustack.api.exceptions import ForbiddenException

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/worker/{worker_id}", response_model=List[WorkerLog])
async def get_worker_logs(
    worker_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of logs to return"
    ),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    severity: Optional[str] = Query(None, description="Filter logs by severity level"),
):
    """
    Get logs for a specific worker.
    """
    # Check if the user has permission to view this worker's logs
    if user.worker and user.worker.id != worker_id:
        raise ForbiddenException(
            message="You don't have permission to view this worker's logs"
        )

    # Build query
    statement = select(WorkerLog).where(WorkerLog.worker_id == worker_id)

    # Apply filters
    if severity:
        statement = statement.where(WorkerLog.severity == severity)

    # Apply pagination and ordering
    statement = (
        statement.order_by(WorkerLog.timestamp.desc()).limit(limit).offset(offset)
    )

    # Execute query
    result = await session.exec(statement)
    return result.all()


@router.get("/gpu/{gpu_id}", response_model=List[GPULog])
async def get_gpu_logs(
    gpu_id: str,
    session: SessionDep,
    user: CurrentUserDep,
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of logs to return"
    ),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    severity: Optional[str] = Query(None, description="Filter logs by severity level"),
):
    """
    Get logs for a specific GPU.
    """
    # Build query
    statement = select(GPULog).where(GPULog.gpu_id == gpu_id)

    # Apply filters
    if severity:
        statement = statement.where(GPULog.severity == severity)

    # Apply pagination and ordering
    statement = statement.order_by(GPULog.timestamp.desc()).limit(limit).offset(offset)

    # Execute query
    result = await session.exec(statement)
    return result.all()


@router.get("/worker/latest/{worker_id}", response_model=WorkerLog)
async def get_latest_worker_log(
    worker_id: int,
    session: SessionDep,
    user: CurrentUserDep,
):
    """
    Get the latest log for a specific worker.
    """
    # Check if the user has permission to view this worker's logs
    if user.worker and user.worker.id != worker_id:
        raise ForbiddenException(
            message="You don't have permission to view this worker's logs"
        )

    # Build query
    statement = select(WorkerLog)
    statement = statement.where(WorkerLog.worker_id == worker_id)
    statement = statement.order_by(WorkerLog.timestamp.desc()).limit(1)

    # Execute query
    result = await session.exec(statement)
    return result.first()


@router.get("/gpu/latest/{gpu_id}", response_model=GPULog)
async def get_latest_gpu_log(
    gpu_id: str,
    session: SessionDep,
    user: CurrentUserDep,
):
    """
    Get the latest log for a specific GPU.
    """
    # Build query
    statement = select(GPULog)
    statement = statement.where(GPULog.gpu_id == gpu_id)
    statement = statement.order_by(GPULog.timestamp.desc()).limit(1)

    # Execute query
    result = await session.exec(statement)
    return result.first()
