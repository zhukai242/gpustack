from typing import List, Optional, Dict
from fastapi import APIRouter, Query, Body
from sqlalchemy import func, and_, text, literal_column
from sqlmodel import select
from gpustack.server.deps import SessionDep, CurrentUserDep
from gpustack.schemas.load import WorkerLog, GPULog, LogTypeEnum
from gpustack.schemas.workers import Worker
from gpustack.api.exceptions import (
    ForbiddenException,
    NotFoundException,
    BadRequestException,
)
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/logs", tags=["logs"])


class LogUpdate(BaseModel):
    """Log update model for processor, comment, and status."""

    processor: Optional[str] = None
    comment: Optional[str] = None
    status: Optional[str] = None


class LogTypeCount(BaseModel):
    """Count of logs by type."""

    log_type: str
    count: int


class SeverityCount(BaseModel):
    """Count of logs by severity."""

    severity: str
    count: int


class DailyLogStats(BaseModel):
    """Daily log statistics."""

    today: List[LogTypeCount]  # Today's log counts by type
    yesterday: List[LogTypeCount]  # Yesterday's log counts by type
    comparison: Dict[str, float]  # Comparison percentage for each type


class TotalLogStats(BaseModel):
    """Total log statistics."""

    total: List[LogTypeCount]  # Total log counts by type
    severity: List[SeverityCount]  # Total log counts by severity


class ExceptionLog(BaseModel):
    """Exception log with associated worker and GPU information."""

    log_id: int  # Log ID
    log_type: Optional[str] = None  # Log type
    severity: Optional[str] = None  # Log severity
    log_content: Optional[str] = None  # Log content
    timestamp: int  # Log timestamp
    worker_name: str  # Associated worker name
    gpu_name: Optional[str] = None  # Associated GPU name (if any)
    processor: Optional[str] = None  # Processor
    comment: Optional[str] = None  # Comment
    log_source: str  # Source of the log: "worker" or "gpu"
    status: Optional[str] = None  # Log status


class ExceptionLogList(BaseModel):
    """List of exception logs with pagination."""

    items: List[ExceptionLog]  # List of exception logs
    total: int  # Total number of exception logs
    page: int  # Current page
    per_page: int  # Items per page
    total_pages: int  # Total number of pages


class ExceptionLogUpdate(BaseModel):
    """Model for updating exception logs with processor and comment."""

    processor: Optional[str] = None  # Processor
    comment: Optional[str] = None  # Comment


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


@router.put("/worker/{log_id}", response_model=WorkerLog)
async def update_worker_log(
    log_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    log_update: LogUpdate = Body(...),
):
    """
    Update a worker log's processor and comment.
    """
    # Get the log first to verify it exists
    statement = select(WorkerLog).where(WorkerLog.id == log_id)
    result = await session.exec(statement)
    log = result.first()

    if not log:
        raise NotFoundException(f"Worker log with ID {log_id} not found")

    # Prepare update data
    update_data = log_update.model_dump(exclude_unset=True)
    if not update_data:
        # Ensure we return a single object, not a tuple
        if isinstance(log, tuple):
            log = log[0]
        return log

    # Update the fields using SQLAlchemy's update statement
    from sqlmodel import update

    stmt = update(WorkerLog).where(WorkerLog.id == log_id).values(**update_data)
    await session.exec(stmt)
    await session.commit()

    # Get the updated log object
    result = await session.exec(select(WorkerLog).where(WorkerLog.id == log_id))
    updated_log = result.first()
    # Ensure we return a single object, not a tuple
    if isinstance(updated_log, tuple):
        updated_log = updated_log[0]
    return updated_log


@router.put("/gpu/{log_id}", response_model=GPULog)
async def update_gpu_log(
    log_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    log_update: LogUpdate = Body(...),
):
    """
    Update a GPU log's processor and comment.
    """
    # Get the log first to verify it exists
    statement = select(GPULog).where(GPULog.id == log_id)
    result = await session.exec(statement)
    log = result.first()

    if not log:
        raise NotFoundException(f"GPU log with ID {log_id} not found")

    # Prepare update data
    update_data = log_update.model_dump(exclude_unset=True)
    if not update_data:
        # Ensure we return a single object, not a tuple
        if isinstance(log, tuple):
            log = log[0]
        return log

    # Update the fields using SQLAlchemy's update statement
    from sqlmodel import update

    stmt = update(GPULog).where(GPULog.id == log_id).values(**update_data)
    await session.exec(stmt)
    await session.commit()

    # Get the updated log object
    result = await session.exec(select(GPULog).where(GPULog.id == log_id))
    updated_log = result.first()
    # Ensure we return a single object, not a tuple
    if isinstance(updated_log, tuple):
        updated_log = updated_log[0]
    return updated_log


@router.get("/daily-stats", response_model=DailyLogStats)
async def get_daily_log_stats(session: SessionDep):
    """
    Get today's log counts by type, compared with yesterday's counts.
    """
    # Define log types using enum
    log_types = [
        LogTypeEnum.STORAGE,
        LogTypeEnum.NETWORK,
        LogTypeEnum.DEVICE_DRIVER,
        LogTypeEnum.MEMORY,
        LogTypeEnum.KERNEL,
        LogTypeEnum.HARDWARE,
    ]

    # Get current date boundaries in UTC
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    yesterday_start = today_start - timedelta(days=1)
    tomorrow_start = today_start + timedelta(days=1)

    # Convert to timestamps
    today_ts = int(today_start.timestamp())
    yesterday_ts = int(yesterday_start.timestamp())
    tomorrow_ts = int(tomorrow_start.timestamp())

    # Initialize result dictionaries
    today_counts = {log_type: 0 for log_type in log_types}
    yesterday_counts = {log_type: 0 for log_type in log_types}

    # Query today's worker logs
    stmt_today_worker = (
        select(WorkerLog.log_type, func.count(WorkerLog.id).label('count'))
        .where(
            and_(
                WorkerLog.timestamp >= today_ts,
                WorkerLog.timestamp < tomorrow_ts,
                WorkerLog.severity.in_(['warning', 'error']),
                WorkerLog.log_type.in_(log_types),
            )
        )
        .group_by(WorkerLog.log_type)
    )

    today_worker_result = await session.exec(stmt_today_worker)
    today_worker_logs = today_worker_result.all()

    # Query today's GPU logs
    stmt_today_gpu = (
        select(GPULog.log_type, func.count(GPULog.id).label('count'))
        .where(
            and_(
                GPULog.timestamp >= today_ts,
                GPULog.timestamp < tomorrow_ts,
                GPULog.severity.in_(['warning', 'error']),
                GPULog.log_type.in_(log_types),
            )
        )
        .group_by(GPULog.log_type)
    )

    today_gpu_result = await session.exec(stmt_today_gpu)
    today_gpu_logs = today_gpu_result.all()

    # Query yesterday's worker logs
    stmt_yesterday_worker = (
        select(WorkerLog.log_type, func.count(WorkerLog.id).label('count'))
        .where(
            and_(
                WorkerLog.timestamp >= yesterday_ts,
                WorkerLog.timestamp < today_ts,
                WorkerLog.severity.in_(['warning', 'error']),
                WorkerLog.log_type.in_(log_types),
            )
        )
        .group_by(WorkerLog.log_type)
    )

    yesterday_worker_result = await session.exec(stmt_yesterday_worker)
    yesterday_worker_logs = yesterday_worker_result.all()

    # Query yesterday's GPU logs
    stmt_yesterday_gpu = (
        select(GPULog.log_type, func.count(GPULog.id).label('count'))
        .where(
            and_(
                GPULog.timestamp >= yesterday_ts,
                GPULog.timestamp < today_ts,
                GPULog.severity.in_(['warning', 'error']),
                GPULog.log_type.in_(log_types),
            )
        )
        .group_by(GPULog.log_type)
    )

    yesterday_gpu_result = await session.exec(stmt_yesterday_gpu)
    yesterday_gpu_logs = yesterday_gpu_result.all()

    # Combine worker and GPU logs for today
    for log in today_worker_logs:
        if log.log_type in today_counts:
            today_counts[log.log_type] += log.count

    for log in today_gpu_logs:
        if log.log_type in today_counts:
            today_counts[log.log_type] += log.count

    # Combine worker and GPU logs for yesterday
    for log in yesterday_worker_logs:
        if log.log_type in yesterday_counts:
            yesterday_counts[log.log_type] += log.count

    for log in yesterday_gpu_logs:
        if log.log_type in yesterday_counts:
            yesterday_counts[log.log_type] += log.count

    # Calculate comparison percentages
    comparison = {}
    for log_type in log_types:
        today = today_counts[log_type]
        yesterday = yesterday_counts[log_type]

        if yesterday == 0:
            # If yesterday had 0, set to 100% if today has any, else 0%
            comparison[log_type] = 100.0 if today > 0 else 0.0
        else:
            # Calculate percentage change
            change = ((today - yesterday) / yesterday) * 100
            comparison[log_type] = round(change, 2)

    # Format results
    today_result = [
        LogTypeCount(log_type=log_type, count=count)
        for log_type, count in today_counts.items()
    ]
    yesterday_result = [
        LogTypeCount(log_type=log_type, count=count)
        for log_type, count in yesterday_counts.items()
    ]

    return DailyLogStats(
        today=today_result, yesterday=yesterday_result, comparison=comparison
    )


@router.get("/total-stats", response_model=TotalLogStats)
async def get_total_log_stats(session: SessionDep):
    """
    Get total log counts by type and severity for all time.
    """
    # Define log types using enum
    log_types = [
        LogTypeEnum.STORAGE,
        LogTypeEnum.NETWORK,
        LogTypeEnum.DEVICE_DRIVER,
        LogTypeEnum.MEMORY,
        LogTypeEnum.KERNEL,
        LogTypeEnum.HARDWARE,
    ]

    # Initialize result dictionaries
    total_counts = {log_type: 0 for log_type in log_types}
    severity_counts = {}

    # Query total worker logs by type
    stmt_worker_type = (
        select(WorkerLog.log_type, func.count(WorkerLog.id).label('count'))
        .where(
            and_(
                WorkerLog.severity.in_(['warning', 'error']),
                WorkerLog.log_type.in_(log_types),
            )
        )
        .group_by(WorkerLog.log_type)
    )

    worker_type_result = await session.exec(stmt_worker_type)
    worker_type_logs = worker_type_result.all()

    # Query total GPU logs by type
    stmt_gpu_type = (
        select(GPULog.log_type, func.count(GPULog.id).label('count'))
        .where(
            and_(
                GPULog.severity.in_(['warning', 'error']),
                GPULog.log_type.in_(log_types),
            )
        )
        .group_by(GPULog.log_type)
    )

    gpu_type_result = await session.exec(stmt_gpu_type)
    gpu_type_logs = gpu_type_result.all()

    # Query total worker logs by severity
    stmt_worker_severity = (
        select(WorkerLog.severity, func.count(WorkerLog.id).label('count'))
        .where(
            and_(
                WorkerLog.severity.in_(['warning', 'error']),
                WorkerLog.log_type.in_(log_types),
            )
        )
        .group_by(WorkerLog.severity)
    )

    worker_severity_result = await session.exec(stmt_worker_severity)
    worker_severity_logs = worker_severity_result.all()

    # Query total GPU logs by severity
    stmt_gpu_severity = (
        select(GPULog.severity, func.count(GPULog.id).label('count'))
        .where(
            and_(
                GPULog.severity.in_(['warning', 'error']),
                GPULog.log_type.in_(log_types),
            )
        )
        .group_by(GPULog.severity)
    )

    gpu_severity_result = await session.exec(stmt_gpu_severity)
    gpu_severity_logs = gpu_severity_result.all()

    # Combine worker and GPU logs by type
    for log in worker_type_logs:
        if log.log_type in total_counts:
            total_counts[log.log_type] += log.count

    for log in gpu_type_logs:
        if log.log_type in total_counts:
            total_counts[log.log_type] += log.count

    # Combine worker and GPU logs by severity
    for log in worker_severity_logs:
        severity_counts[log.severity] = severity_counts.get(log.severity, 0) + log.count

    for log in gpu_severity_logs:
        severity_counts[log.severity] = severity_counts.get(log.severity, 0) + log.count

    # Format results
    total_result = [
        LogTypeCount(log_type=log_type, count=count)
        for log_type, count in total_counts.items()
    ]

    severity_result = [
        SeverityCount(severity=severity, count=count)
        for severity, count in severity_counts.items()
    ]

    return TotalLogStats(total=total_result, severity=severity_result)


@router.get("/exceptions", response_model=ExceptionLogList)
async def get_exception_logs(
    session: SessionDep,
    user: CurrentUserDep,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    log_type: Optional[str] = Query(None, description="Log type to filter by"),
    keyword: Optional[str] = Query(
        None, description="Keyword to search in log content"
    ),
    severity: Optional[str] = Query(None, description="Severity to filter by"),
    log_source: Optional[str] = Query(
        None, description="Log source: 'worker' or 'gpu'"
    ),
):
    """
    Get paginated exception logs with worker and GPU information.
    Supports filtering by log type, keyword, severity, and log source.
    """
    # Create a union query for worker and GPU logs
    # First, query worker logs with all columns that match GPU logs
    worker_logs_query = (
        select(
            WorkerLog.id.label('log_id'),
            WorkerLog.log_type,
            WorkerLog.severity,
            WorkerLog.log_content,
            WorkerLog.timestamp,
            Worker.name.label('worker_name'),
            WorkerLog.processor,
            WorkerLog.comment,
            # Use literal_column with explicit string literal
            literal_column("'worker'").label('log_source'),
            # Use CAST to ensure consistent type with GPU logs
            literal_column("CAST(NULL AS VARCHAR)").label('gpu_name'),
            WorkerLog.status,
        )
        .join(Worker, Worker.id == WorkerLog.worker_id)
        .where(WorkerLog.severity.in_(['warning', 'error']))
    )

    # Then, query GPU logs
    gpu_logs_query = (
        select(
            GPULog.id.label('log_id'),
            GPULog.log_type,
            GPULog.severity,
            GPULog.log_content,
            GPULog.timestamp,
            Worker.name.label('worker_name'),
            GPULog.processor,
            GPULog.comment,
            # Use literal_column with explicit string literal
            literal_column("'gpu'").label('log_source'),
            # Use GPU ID as gpu_name
            GPULog.gpu_id.label('gpu_name'),
            GPULog.status,
        )
        .join(Worker, Worker.id == GPULog.worker_id)
        .where(GPULog.severity.in_(['warning', 'error']))
    )

    # Combine both queries
    union_query = worker_logs_query.union_all(gpu_logs_query)

    # Apply filters
    if log_type:
        # Apply log_type filter to both worker and GPU logs
        worker_logs_query = worker_logs_query.where(WorkerLog.log_type == log_type)
        gpu_logs_query = gpu_logs_query.where(GPULog.log_type == log_type)
        union_query = worker_logs_query.union_all(gpu_logs_query)

    if severity:
        # Apply severity filter to both worker and GPU logs
        worker_logs_query = worker_logs_query.where(WorkerLog.severity == severity)
        gpu_logs_query = gpu_logs_query.where(GPULog.severity == severity)
        union_query = worker_logs_query.union_all(gpu_logs_query)

    if keyword:
        # Apply keyword filter to both worker and GPU logs
        worker_logs_query = worker_logs_query.where(
            WorkerLog.log_content.like(f"%{keyword}%")
        )
        gpu_logs_query = gpu_logs_query.where(GPULog.log_content.like(f"%{keyword}%"))
        union_query = worker_logs_query.union_all(gpu_logs_query)

    if log_source:
        # Apply log_source filter
        if log_source == 'worker':
            union_query = worker_logs_query
        elif log_source == 'gpu':
            union_query = gpu_logs_query

    # Count total records
    count_query = select(func.count()).select_from(union_query.subquery())
    total_count = await session.scalar(count_query)

    # Apply pagination
    offset = (page - 1) * per_page
    paginated_query = (
        union_query.order_by(text('timestamp desc')).offset(offset).limit(per_page)
    )

    # Execute query
    result = await session.exec(paginated_query)
    logs = result.all()

    # Calculate total pages
    total_pages = (total_count + per_page - 1) // per_page

    # Format results - use index access for tuple results
    exception_logs = [
        ExceptionLog(
            log_id=log[0],  # log_id
            log_type=log[1],  # log_type
            severity=log[2],  # severity
            log_content=log[3],  # log_content
            timestamp=log[4],  # timestamp
            worker_name=log[5],  # worker_name
            gpu_name=log[9],  # gpu_name (position 9 in the select)
            processor=log[6],  # processor
            comment=log[7],  # comment
            log_source=log[8],  # log_source
            status=log[10],  # status (position 10 in the select)
        )
        for log in logs
    ]

    return ExceptionLogList(
        items=exception_logs,
        total=total_count,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.put("/exceptions/{log_source}/{log_id}")
async def update_exception_log(
    log_source: str,
    log_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    log_update: ExceptionLogUpdate = Body(...),
):
    """
    Update an exception log with processor and comment.

    Args:
        log_source: Source of the log, either 'worker' or 'gpu'
        log_id: ID of the log to update
        session: Database session
        user: Current user
        log_update: Update data containing processor and comment
    """
    # Determine which log table to use based on log_source
    if log_source == 'worker':
        log_model = WorkerLog
    elif log_source == 'gpu':
        log_model = GPULog
    else:
        raise BadRequestException(
            f"Invalid log_source: {log_source}. Must be 'worker' or 'gpu'"
        )

    # Get the log
    stmt = select(log_model).where(log_model.id == log_id)
    result = await session.exec(stmt)
    log = result.first()

    if not log:
        raise NotFoundException(
            f"{log_source.capitalize()} log with ID {log_id} not found"
        )

    # Update the log with processor and comment
    update_data = log_update.model_dump(exclude_unset=True)
    if update_data:
        # Use SQL UPDATE statement to update the record
        from sqlmodel import update

        stmt = update(log_model).where(log_model.id == log_id).values(**update_data)
        await session.exec(stmt)
        await session.commit()
        await session.refresh(log)

    return {
        "message": f"{log_source.capitalize()} log updated successfully",
        "log_id": log_id,
    }
