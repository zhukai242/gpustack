from typing import Optional
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from gpustack.api.exceptions import (
    AlreadyExistsException,
    NotFoundException,
)
from gpustack.server.deps import SessionDep, EngineDep
from gpustack.schemas.rack import (
    RackCreate,
    RackListParams,
    RackPublic,
    RackUpdate,
    RacksPublic,
    Rack,
    RackWithWorkersAndGPUs,
    WorkerWithGPUs,
    GPUDeviceInfo,
    RacksWithWorkersAndGPUs,
    ClusterStats,
    ComparisonData,
    UtilizationData,
    AlertData,
)
from gpustack.schemas.load import WorkerLoad, WorkerLog, GPULog
from gpustack.schemas.workers import Worker


router = APIRouter()


@router.post("", response_model=RackPublic, status_code=201)
async def create_rack(rack_create: RackCreate, session: SessionDep):
    """Create a new rack."""
    # Check if rack with the same name already exists in the cluster
    existing_rack = await Rack.one_by_fields(
        session,
        fields={
            'name': rack_create.name,
            'cluster_id': rack_create.cluster_id,
            'deleted_at': None,
        },
    )
    if existing_rack:
        raise AlreadyExistsException(
            f"Rack '{rack_create.name}' already exists in cluster {rack_create.cluster_id}"
        )

    # Create the rack
    rack = Rack(**rack_create.model_dump())
    await rack.save(session)
    return rack


@router.get("", response_model=RacksPublic)
async def list_racks(
    session: SessionDep,
    engine: EngineDep,
    params: RackListParams = Depends(),
    name: Optional[str] = None,
    cluster_id: Optional[int] = None,
):
    """List all racks."""
    fields = {"deleted_at": None}
    if name:
        fields["name"] = name
    if cluster_id:
        fields["cluster_id"] = cluster_id

    if params.watch:
        return StreamingResponse(
            Rack.streaming(engine, fields=fields),
            media_type="text/event-stream",
        )

    return await Rack.paginated_by_query(
        session=session,
        fields=fields,
        page=params.page,
        per_page=params.perPage,
        order_by=params.order_by,
    )


@router.get("/with-workers-gpus", response_model=RacksWithWorkersAndGPUs)
async def get_racks_with_workers_and_gpus(
    session: SessionDep,
    cluster_id: int,
):
    """Get all racks with workers and GPU devices information for a cluster."""
    # Get all racks in the specified cluster
    racks = await Rack.all_by_fields(
        session, fields={'cluster_id': cluster_id, 'deleted_at': None}
    )

    result = []

    for rack in racks:
        # Get all workers in the rack
        workers = await Worker.all_by_fields(
            session, fields={'rack_id': rack.id, 'deleted_at': None}
        )

        rack_workers = []
        total_gpus = 0

        for worker in workers:
            gpu_devices = []
            gpu_count = 0

            # Get GPU devices information from worker status
            if (
                worker.status
                and hasattr(worker.status, 'gpu_devices')
                and worker.status.gpu_devices
            ):
                for gpu in worker.status.gpu_devices:
                    gpu_devices.append(
                        GPUDeviceInfo(
                            index=gpu.index,
                            device_index=gpu.device_index,
                            device_chip_index=gpu.device_chip_index,
                            vendor=gpu.vendor,
                            type=gpu.type,
                            memory=gpu.memory.model_dump() if gpu.memory else None,
                            core=gpu.core.model_dump() if gpu.core else None,
                        )
                    )
                gpu_count = len(gpu_devices)
                total_gpus += gpu_count

            rack_workers.append(
                WorkerWithGPUs(
                    id=worker.id,
                    name=worker.name,
                    state=worker.state.value if worker.state else None,
                    ip=worker.ip,
                    gpu_devices=gpu_devices,
                    gpus=gpu_count,
                )
            )

        result.append(
            RackWithWorkersAndGPUs(
                id=rack.id,
                name=rack.name,
                cluster_id=rack.cluster_id,
                description=rack.description,
                workers=rack_workers,
                total_workers=len(rack_workers),
                total_gpus=total_gpus,
            )
        )

    return RacksWithWorkersAndGPUs(racks=result)


@router.get("/{rack_id}", response_model=RackPublic)
async def get_rack(rack_id: int, session: SessionDep):
    """Get a rack by ID."""
    rack = await Rack.one_by_id(session, rack_id)
    if not rack or rack.deleted_at:
        raise NotFoundException(f"Rack with ID {rack_id} not found")
    return rack


@router.put("/{rack_id}", response_model=RackPublic)
async def update_rack(rack_id: int, rack_update: RackUpdate, session: SessionDep):
    """Update a rack."""
    rack = await Rack.one_by_id(session, rack_id)
    if not rack or rack.deleted_at:
        raise NotFoundException(f"Rack with ID {rack_id} not found")

    # Check if updated name already exists in the cluster
    if rack_update.name and rack_update.name != rack.name:
        existing_rack = await Rack.one_by_fields(
            session,
            fields={
                'name': rack_update.name,
                'cluster_id': rack.cluster_id,
                'deleted_at': None,
            },
        )
        if existing_rack:
            raise AlreadyExistsException(
                f"Rack '{rack_update.name}' already exists in cluster {rack.cluster_id}"
            )

    # Update the rack
    update_data = rack_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rack, key, value)
    await rack.save(session)
    return rack


@router.delete("/{rack_id}", status_code=204)
async def delete_rack(rack_id: int, session: SessionDep):
    """Delete a rack."""
    rack = await Rack.one_by_id(session, rack_id)
    if not rack or rack.deleted_at:
        raise NotFoundException(f"Rack with ID {rack_id} not found")

    await rack.delete(session)
    return Response(status_code=204)


@router.get("/cluster/{cluster_id}", response_model=RacksPublic)
async def get_racks_by_cluster(
    cluster_id: int,
    session: SessionDep,
    engine: EngineDep,
    params: RackListParams = Depends(),
):
    """Get all racks for a cluster."""
    fields = {"cluster_id": cluster_id, "deleted_at": None}

    if params.watch:
        return StreamingResponse(
            Rack.streaming(engine, fields=fields),
            media_type="text/event-stream",
        )

    return await Rack.paginated_by_query(
        session=session,
        fields=fields,
        page=params.page,
        per_page=params.perPage,
        order_by=params.order_by,
    )


@router.get("/cluster/{cluster_id}/stats", response_model=ClusterStats)
async def get_cluster_stats(cluster_id: int, session: SessionDep):
    """Get cluster statistics including worker count, device status, utilization, and alerts."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, func

    # Calculate time ranges for current and previous month
    now = datetime.now(timezone.utc)  # Use timezone-aware datetime
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)

    # Get all workers in the cluster
    workers = await Worker.all_by_fields(
        session, fields={'cluster_id': cluster_id, 'deleted_at': None}
    )

    # Calculate total workers current month vs previous month
    current_total = len(workers)

    # For previous month, we need to query from database
    # Use SQLAlchemy's func.now() to get current time in database timezone
    stmt_prev_total = select(func.count(Worker.id)).where(
        Worker.cluster_id == cluster_id,
        Worker.deleted_at.is_(None),
        Worker.created_at <= previous_month_end,
    )
    result = await session.exec(stmt_prev_total)
    previous_total = result.scalar_one()  # Use scalar_one() to get integer value

    # Calculate growth rate
    growth_total = 0.0
    if previous_total > 0:
        growth_total = ((current_total - previous_total) / previous_total) * 100
    elif current_total > 0:  # From 0 to something, 100% growth
        growth_total = 100.0

    # Calculate online/offline workers
    online_states = {'ready', 'initializing'}
    online_workers = [w for w in workers if w.state and w.state.value in online_states]
    offline_workers = [
        w for w in workers if w.state and w.state.value not in online_states
    ]

    current_online = len(online_workers)
    current_offline = len(offline_workers)

    # Calculate previous month online/offline workers
    # (simplified: count workers that existed last month)
    stmt_prev_online = select(func.count(Worker.id)).where(
        Worker.cluster_id == cluster_id,
        Worker.deleted_at.is_(None),
        Worker.created_at <= previous_month_end,
        Worker.state.in_(online_states),
    )
    result = await session.exec(stmt_prev_online)
    previous_online = result.scalar_one()  # Use scalar_one() to get integer value
    previous_offline = previous_total - previous_online

    growth_online = 0.0
    if previous_online > 0:
        growth_online = ((current_online - previous_online) / previous_online) * 100
    elif current_online > 0:  # From 0 to something, 100% growth
        growth_online = 100.0

    growth_offline = 0.0
    if previous_offline > 0:
        growth_offline = ((current_offline - previous_offline) / previous_offline) * 100
    elif current_offline > 0:  # From 0 to something, 100% growth
        growth_offline = 100.0

    # Calculate average utilization from WorkerLoad
    stmt_utilization = (
        select(
            func.avg(WorkerLoad.cpu).label('avg_cpu'),
            func.avg(WorkerLoad.ram).label('avg_ram'),
            func.avg(WorkerLoad.gpu).label('avg_gpu'),
            func.avg(WorkerLoad.vram).label('avg_vram'),
        )
        .join(Worker, WorkerLoad.worker_id == Worker.id)
        .where(
            Worker.cluster_id == cluster_id,
            Worker.deleted_at.is_(None),
            WorkerLoad.timestamp >= int(current_month_start.timestamp()),
        )
    )
    utilization_result = await session.exec(stmt_utilization)
    utilization = utilization_result.one()

    # Calculate alerts
    current_time = int(now.timestamp())
    previous_month_time = int(previous_month_start.timestamp())

    # Get worker logs alerts
    stmt_worker_alerts = select(func.count(WorkerLog.id)).where(
        WorkerLog.worker_id.in_([w.id for w in workers]),
        WorkerLog.severity.in_(['warning', 'error']),
        WorkerLog.timestamp >= current_time - 86400 * 30,  # last 30 days
    )
    stmt_gpu_alerts = select(func.count(GPULog.id)).where(
        GPULog.worker_id.in_([w.id for w in workers]),
        GPULog.severity.in_(['warning', 'error']),
        GPULog.timestamp >= current_time - 86400 * 30,  # last 30 days
    )

    worker_alerts = await session.exec(stmt_worker_alerts)
    gpu_alerts = await session.exec(stmt_gpu_alerts)
    total_alerts = worker_alerts.scalar_one() + gpu_alerts.scalar_one()

    # Get unprocessed alerts (assuming status is 'unprocessed' for unhandled alerts)
    stmt_unprocessed = select(func.count(WorkerLog.id)).where(
        WorkerLog.worker_id.in_([w.id for w in workers]),
        WorkerLog.severity.in_(['warning', 'error']),
        WorkerLog.status == 'unprocessed',
        WorkerLog.timestamp >= current_time - 86400 * 30,  # last 30 days
    )
    unprocessed_alerts = await session.exec(stmt_unprocessed)
    total_unprocessed = unprocessed_alerts.scalar_one()

    # Get previous month alerts
    stmt_prev_worker_alerts = select(func.count(WorkerLog.id)).where(
        WorkerLog.worker_id.in_([w.id for w in workers]),
        WorkerLog.severity.in_(['warning', 'error']),
        WorkerLog.timestamp >= previous_month_time,
        WorkerLog.timestamp < int(current_month_start.timestamp()),
    )
    stmt_prev_gpu_alerts = select(func.count(GPULog.id)).where(
        GPULog.worker_id.in_([w.id for w in workers]),
        GPULog.severity.in_(['warning', 'error']),
        GPULog.timestamp >= previous_month_time,
        GPULog.timestamp < int(current_month_start.timestamp()),
    )

    prev_worker_alerts = await session.exec(stmt_prev_worker_alerts)
    prev_gpu_alerts = await session.exec(stmt_prev_gpu_alerts)
    prev_total_alerts = prev_worker_alerts.scalar_one() + prev_gpu_alerts.scalar_one()

    growth_alerts = 0.0
    if prev_total_alerts > 0:
        growth_alerts = ((total_alerts - prev_total_alerts) / prev_total_alerts) * 100
    elif total_alerts > 0:  # From 0 to something, 100% growth
        growth_alerts = 100.0

    # Calculate resource saturation (simple average of utilization percentages)
    saturation = 0.0
    util_values = [
        v
        for v in [
            utilization.avg_cpu,
            utilization.avg_ram,
            utilization.avg_gpu,
            utilization.avg_vram,
        ]
        if v is not None
    ]
    if util_values:
        saturation = sum(util_values) / len(util_values)

    # Create response
    stats = ClusterStats(
        total_workers=ComparisonData(
            current=current_total, previous=previous_total, growth=growth_total
        ),
        online_workers=ComparisonData(
            current=current_online, previous=previous_online, growth=growth_online
        ),
        offline_workers=ComparisonData(
            current=current_offline, previous=previous_offline, growth=growth_offline
        ),
        utilization=UtilizationData(
            cpu=utilization.avg_cpu or 0.0,
            ram=utilization.avg_ram or 0.0,
            gpu=utilization.avg_gpu or 0.0,
            vram=utilization.avg_vram or 0.0,
        ),
        alerts=AlertData(
            total=total_alerts,
            unprocessed=total_unprocessed,
            comparison=ComparisonData(
                current=total_alerts, previous=prev_total_alerts, growth=growth_alerts
            ),
        ),
        resource_saturation=saturation,
    )

    return stats
