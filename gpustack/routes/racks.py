from typing import Optional, List
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
    RackGPUHealthResponse,
    RackGPUHealthStats,
    GPUModeHealthStats,
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


@router.get("/heatmap")
async def get_heatmap(
    session: SessionDep,
    cluster_id: int,
    rack_level: Optional[bool] = None,
    node_level: Optional[bool] = None,
):
    """
    Get heatmap data for cluster resources.

    Args:
        session: Database session dependency
        cluster_id: ID of the cluster to get heatmap for
        rack_level: Whether to include rack-level heatmap data
        node_level: Whether to include node-level heatmap data

    Returns:
        HeatmapResponse containing requested heatmap data
    """
    from gpustack.schemas.rack import (
        HeatmapResponse,
        RackHeatmapData,
        NodeHeatmapData,
        GPUHeatmapData,
    )

    # Get all racks in the specified cluster
    racks = await Rack.all_by_fields(
        session, fields={'cluster_id': cluster_id, 'deleted_at': None}
    )

    # Get all workers in the specified cluster
    workers = await Worker.all_by_fields(
        session, fields={'cluster_id': cluster_id, 'deleted_at': None}
    )

    # Initialize response data
    rack_heatmap_data = []
    node_heatmap_data = []

    # Iterate through racks and build heatmap data
    for rack in racks:
        # Get workers in this rack
        rack_workers = [worker for worker in workers if worker.rack_id == rack.id]

        # Process rack-level heatmap if requested
        if rack_level:
            rack_nodes = []

            for worker in rack_workers:
                # Build GPU heatmap data for this worker
                gpu_data = []
                if (
                    worker.status
                    and hasattr(worker.status, 'gpu_devices')
                    and worker.status.gpu_devices
                ):
                    for gpu in worker.status.gpu_devices:
                        # Get GPU core utilization
                        gpu_util = gpu.core.utilization_rate if gpu.core else 0.0
                        # Get GPU memory utilization
                        vram_util = gpu.memory.utilization_rate if gpu.memory else 0.0

                        gpu_data.append(
                            GPUHeatmapData(
                                index=gpu.index,
                                device_id=f"{worker.name}:{gpu.type}:{gpu.index}",
                                gpu_utilization=gpu_util,
                                vram_utilization=vram_util,
                                gpu_type=gpu.type,
                            )
                        )

                # Get CPU utilization
                cpu_util = (
                    worker.status.cpu.utilization_rate
                    if (worker.status and worker.status.cpu)
                    else 0.0
                )
                # Get RAM utilization
                ram_util = (
                    worker.status.memory.utilization_rate
                    if (worker.status and worker.status.memory)
                    else 0.0
                )

                # Build node heatmap data for this worker
                node_data = NodeHeatmapData(
                    node_id=worker.id,
                    node_name=worker.name,
                    rack_id=rack.id,
                    rack_name=rack.name,
                    cpu_utilization=cpu_util,
                    ram_utilization=ram_util,
                    gpus=gpu_data,
                )
                rack_nodes.append(node_data)

            # Build rack heatmap data
            rack_heatmap_item = RackHeatmapData(
                rack_id=rack.id,
                rack_name=rack.name,
                nodes=rack_nodes,
            )
            rack_heatmap_data.append(rack_heatmap_item)

        # Process node-level heatmap if requested
        if node_level:
            for worker in rack_workers:
                # Build GPU heatmap data for this worker
                gpu_data = []
                if (
                    worker.status
                    and hasattr(worker.status, 'gpu_devices')
                    and worker.status.gpu_devices
                ):
                    for gpu in worker.status.gpu_devices:
                        # Get GPU core utilization
                        gpu_util = gpu.core.utilization_rate if gpu.core else 0.0
                        # Get GPU memory utilization
                        vram_util = gpu.memory.utilization_rate if gpu.memory else 0.0

                        gpu_data.append(
                            GPUHeatmapData(
                                index=gpu.index,
                                device_id=f"{worker.name}:{gpu.type}:{gpu.index}",
                                gpu_utilization=gpu_util,
                                vram_utilization=vram_util,
                                gpu_type=gpu.type,
                            )
                        )

                # Get CPU utilization
                cpu_util = (
                    worker.status.cpu.utilization_rate
                    if (worker.status and worker.status.cpu)
                    else 0.0
                )
                # Get RAM utilization
                ram_util = (
                    worker.status.memory.utilization_rate
                    if (worker.status and worker.status.memory)
                    else 0.0
                )

                # Build node heatmap data
                node_data = NodeHeatmapData(
                    node_id=worker.id,
                    node_name=worker.name,
                    rack_id=rack.id,
                    rack_name=rack.name,
                    cpu_utilization=cpu_util,
                    ram_utilization=ram_util,
                    gpus=gpu_data,
                )
                node_heatmap_data.append(node_data)

    # Create response
    response = HeatmapResponse(
        cluster_id=cluster_id,
        rack_heatmap=rack_heatmap_data if rack_level else None,
        node_heatmap=node_heatmap_data if node_level else None,
    )

    return response


@router.get("/gpu-utilization")
async def get_rack_gpu_utilization(
    session: SessionDep,
    cluster_id: Optional[int] = None,
):
    """
    Get average GPU utilization statistics for each rack.

    Args:
        session: Database session dependency
        cluster_id: Optional cluster ID to filter racks

    Returns:
        RackGPUUtilizationResponse containing rack-level GPU utilization statistics
    """
    from gpustack.schemas.rack import (
        RackGPUUtilization,
        RackGPUUtilizationResponse,
    )

    # Get all racks with optional cluster filter
    fields = {'deleted_at': None}
    if cluster_id:
        fields['cluster_id'] = cluster_id
    racks = await Rack.all_by_fields(session, fields=fields)

    # Get all workers with optional cluster filter
    worker_fields = {'deleted_at': None}
    if cluster_id:
        worker_fields['cluster_id'] = cluster_id
    workers = await Worker.all_by_fields(session, fields=worker_fields)

    # Initialize response data
    rack_gpu_utilizations = []

    # Iterate through racks and calculate average GPU utilization
    for rack in racks:
        # Get workers in this rack
        rack_workers = [worker for worker in workers if worker.rack_id == rack.id]

        total_gpu_util = 0.0
        total_vram_util = 0.0
        gpu_count = 0

        for worker in rack_workers:
            if (
                worker.status
                and hasattr(worker.status, 'gpu_devices')
                and worker.status.gpu_devices
            ):
                for gpu in worker.status.gpu_devices:
                    # Accumulate GPU utilization
                    if gpu.core and gpu.core.utilization_rate is not None:
                        total_gpu_util += gpu.core.utilization_rate
                        gpu_count += 1
                    # Accumulate VRAM utilization
                    if gpu.memory and gpu.memory.utilization_rate is not None:
                        total_vram_util += gpu.memory.utilization_rate

        # Calculate averages
        avg_gpu_util = total_gpu_util / gpu_count if gpu_count > 0 else 0.0
        avg_vram_util = total_vram_util / gpu_count if gpu_count > 0 else 0.0

        # Build rack GPU utilization data
        rack_utilization = RackGPUUtilization(
            rack_id=rack.id,
            rack_name=rack.name,
            avg_gpu_utilization=round(avg_gpu_util, 1),
            avg_vram_utilization=round(avg_vram_util, 1),
        )

        rack_gpu_utilizations.append(rack_utilization)

    # Create response
    return RackGPUUtilizationResponse(rack_gpu_utilizations=rack_gpu_utilizations)


def _get_rack_workers(workers: List[Worker], rack_id: int) -> List[Worker]:
    """Get workers in a specific rack."""
    return [worker for worker in workers if worker.rack_id == rack_id]


def _collect_gpu_ids(rack_workers: List[Worker]) -> List[str]:
    """Collect all GPU IDs in a list of workers."""
    all_gpu_ids = []
    for worker in rack_workers:
        if (
            worker.status
            and hasattr(worker.status, 'gpu_devices')
            and worker.status.gpu_devices
        ):
            for gpu in worker.status.gpu_devices:
                all_gpu_ids.append(f"{worker.name}:{gpu.type}:{gpu.index}")
    return all_gpu_ids


async def _get_gpu_log_counts(session, gpu_ids: List[str], thirty_days_ago: int):
    """Get GPU log counts for warnings and errors in the last 30 days."""
    from sqlalchemy import select, func

    stmt_gpu_logs = (
        select(GPULog.gpu_id, GPULog.severity, func.count(GPULog.id).label('count'))
        .where(
            GPULog.gpu_id.in_(gpu_ids),
            GPULog.timestamp >= thirty_days_ago,
            GPULog.severity.in_(['warning', 'error']),
        )
        .group_by(GPULog.gpu_id, GPULog.severity)
    )

    gpu_logs_result = await session.exec(stmt_gpu_logs)
    gpu_logs = gpu_logs_result.all()

    # Create a dictionary to store log counts per GPU
    gpu_log_counts = {}
    for log in gpu_logs:
        if log.gpu_id not in gpu_log_counts:
            gpu_log_counts[log.gpu_id] = {'warning': 0, 'error': 0}
        gpu_log_counts[log.gpu_id][log.severity] = log.count

    return gpu_log_counts


def _collect_gpu_model_health(rack_workers: List[Worker], gpu_log_counts: dict):
    """Collect GPU model health data from rack workers."""
    # Dictionary to store GPU architecture family health data
    # Key: arch_family, Value: dict with gpu_type, count, temperatures, warnings, errors
    gpu_model_health = {}

    for worker in rack_workers:
        if (
            worker.status
            and hasattr(worker.status, 'gpu_devices')
            and worker.status.gpu_devices
        ):
            for gpu in worker.status.gpu_devices:
                arch_family = gpu.arch_family or "unknown"
                gpu_type = gpu.type or "unknown"
                gpu_id = f"{worker.name}:{gpu.type}:{gpu.index}"

                # Initialize architecture family data if not exists
                if arch_family not in gpu_model_health:
                    gpu_model_health[arch_family] = {
                        'gpu_type': gpu_type,  # Store first encountered gpu_type as reference
                        'count': 0,
                        'temperatures': [],
                        'warnings': 0,
                        'errors': 0,
                    }

                # Increment GPU count for this architecture family
                gpu_model_health[arch_family]['count'] += 1

                # Get GPU temperature from worker status
                temperature = 0.0
                # Check if GPU has temperature data
                if (
                    gpu.temperature
                    and hasattr(gpu, 'temperature')
                    and gpu.temperature is not None
                ):
                    temperature = gpu.temperature
                gpu_model_health[arch_family]['temperatures'].append(temperature)

                # Get log counts for this GPU
                log_counts = gpu_log_counts.get(gpu_id, {'warning': 0, 'error': 0})
                gpu_model_health[arch_family]['warnings'] += log_counts['warning']
                gpu_model_health[arch_family]['errors'] += log_counts['error']

    return gpu_model_health


def _calculate_gpu_model_stats(gpu_model_health: dict):
    """Calculate GPU model health statistics."""
    gpu_models = []
    for arch_family, health_data in gpu_model_health.items():
        # Calculate average temperature
        avg_temperature = 0.0
        if health_data['temperatures']:
            avg_temperature = sum(health_data['temperatures']) / len(
                health_data['temperatures']
            )

        # Calculate health score (100 - 2*warnings - 5*errors, min 0, max 100)
        health_score = 100 - (health_data['warnings'] * 2) - (health_data['errors'] * 5)
        health_score = max(0.0, min(100.0, health_score))

        # Create GPU model health stats
        gpu_model_stats = GPUModeHealthStats(
            arch_family=arch_family,
            gpu_type=health_data['gpu_type'],
            count=health_data['count'],
            avg_temperature=round(avg_temperature, 1),
            total_warnings=health_data['warnings'],
            total_errors=health_data['errors'],
            health_score=round(health_score, 1),
        )
        gpu_models.append(gpu_model_stats)

    return gpu_models


@router.get("/gpu-health", response_model=RackGPUHealthResponse)
async def get_rack_gpu_health(
    session: SessionDep,
    cluster_id: Optional[int] = None,
):
    """Get GPU health statistics by rack and GPU model, including
    health score and temperature."""
    from datetime import datetime, timezone

    # Get all racks with optional cluster filter
    fields = {'deleted_at': None}
    if cluster_id:
        fields['cluster_id'] = cluster_id
    racks = await Rack.all_by_fields(session, fields=fields)

    # Get all workers with optional cluster filter
    worker_fields = {'deleted_at': None}
    if cluster_id:
        worker_fields['cluster_id'] = cluster_id
    workers = await Worker.all_by_fields(session, fields=worker_fields)

    # Get current timestamp for log query (last 30 days)
    current_time = int(datetime.now(timezone.utc).timestamp())
    thirty_days_ago = current_time - 86400 * 30

    # Initialize response data
    rack_gpu_health = []

    # Iterate through racks and calculate GPU health statistics by model
    for rack in racks:
        # Get workers in this rack
        rack_workers = _get_rack_workers(workers, rack.id)

        if not rack_workers:
            continue

        # Get all GPU IDs in this rack for log query
        all_gpu_ids = _collect_gpu_ids(rack_workers)

        if not all_gpu_ids:
            continue

        # Query GPU logs for this rack's GPUs
        gpu_log_counts = await _get_gpu_log_counts(
            session, all_gpu_ids, thirty_days_ago
        )

        # Collect GPU model health data
        gpu_model_health = _collect_gpu_model_health(rack_workers, gpu_log_counts)

        if not gpu_model_health:
            continue

        # Calculate health score and average temperature for each architecture family
        gpu_models = _calculate_gpu_model_stats(gpu_model_health)

        # Create rack GPU health stats
        rack_health_stats = RackGPUHealthStats(
            rack_id=rack.id, rack_name=rack.name, gpu_models=gpu_models
        )
        rack_gpu_health.append(rack_health_stats)

    # Create response
    response = RackGPUHealthResponse(rack_gpu_health=rack_gpu_health)

    return response


@router.get("/gpu-model-utilization")
async def get_rack_gpu_model_utilization(
    session: SessionDep,
    cluster_id: Optional[int] = None,
):
    """
    Get GPU utilization statistics by model for each rack.

    Args:
        session: Database session dependency
        cluster_id: Optional cluster ID to filter racks

    Returns:
        RackGPUModelUtilizationResponse containing rack-level GPU model utilization statistics
    """
    from gpustack.schemas.rack import (
        GPUModelUtilization,
        RackGPUModelUtilization,
        RackGPUModelUtilizationResponse,
    )

    # Get all racks with optional cluster filter
    fields = {'deleted_at': None}
    if cluster_id:
        fields['cluster_id'] = cluster_id
    racks = await Rack.all_by_fields(session, fields=fields)

    # Get all workers with optional cluster filter
    worker_fields = {'deleted_at': None}
    if cluster_id:
        worker_fields['cluster_id'] = cluster_id
    workers = await Worker.all_by_fields(session, fields=worker_fields)

    # Initialize response data
    rack_gpu_model_utilizations = []

    # Iterate through racks and calculate GPU model utilization
    for rack in racks:
        # Get workers in this rack
        rack_workers = [worker for worker in workers if worker.rack_id == rack.id]

        # Dictionary to store GPU model utilization data
        # Key: gpu_type, Value: tuple(total_gpu_util, total_vram_util, count)
        gpu_model_data = {}

        for worker in rack_workers:
            if (
                worker.status
                and hasattr(worker.status, 'gpu_devices')
                and worker.status.gpu_devices
            ):
                for gpu in worker.status.gpu_devices:
                    # Combine type and arch_family for more detailed GPU identification
                    gpu_type_part = gpu.type or "unknown"
                    arch_family_part = f":{gpu.arch_family}" if gpu.arch_family else ""
                    gpu_type = f"{gpu_type_part}{arch_family_part}"

                    # Initialize model data if not exists
                    if gpu_type not in gpu_model_data:
                        gpu_model_data[gpu_type] = (0.0, 0.0, 0)

                    total_gpu, total_vram, count = gpu_model_data[gpu_type]

                    # Accumulate GPU utilization
                    if gpu.core and gpu.core.utilization_rate is not None:
                        total_gpu += gpu.core.utilization_rate
                    # Accumulate VRAM utilization
                    if gpu.memory and gpu.memory.utilization_rate is not None:
                        total_vram += gpu.memory.utilization_rate

                    # Increment count
                    count += 1

                    gpu_model_data[gpu_type] = (total_gpu, total_vram, count)

        # Build GPU model utilization list
        gpu_models = []
        for gpu_type, (total_gpu, total_vram, count) in gpu_model_data.items():
            avg_gpu_util = total_gpu / count if count > 0 else 0.0
            avg_vram_util = total_vram / count if count > 0 else 0.0

            gpu_models.append(
                GPUModelUtilization(
                    gpu_type=gpu_type,
                    count=count,
                    avg_gpu_utilization=round(avg_gpu_util, 1),
                    avg_vram_utilization=round(avg_vram_util, 1),
                )
            )

        # Build rack GPU model utilization data
        rack_model_utilization = RackGPUModelUtilization(
            rack_id=rack.id,
            rack_name=rack.name,
            gpu_models=gpu_models,
        )

        rack_gpu_model_utilizations.append(rack_model_utilization)

    # Create response
    return RackGPUModelUtilizationResponse(
        rack_gpu_model_utilizations=rack_gpu_model_utilizations
    )


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
