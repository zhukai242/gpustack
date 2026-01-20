from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from gpustack.api.exceptions import (
    NotFoundException,
    BadRequestException,
)
from gpustack.server.deps import SessionDep, EngineDep, get_admin_user, CurrentUserDep
from gpustack.schemas.tenants import (
    TenantResourceCreate,
    TenantResourceUpdate,
    TenantResourcePublic,
    TenantResourcesPublic,
    TenantResourceListParams,
    TenantResource,
    TenantResourceAdjustmentCreate,
    TenantResourceAdjustmentPublic,
    TenantResourceAdjustmentsPublic,
    TenantResourceAdjustmentListParams,
    TenantResourceAdjustment,
    TenantResourceUsageDetailCreate,
    TenantResourceUsageDetailPublic,
    TenantResourceUsageDetailsPublic,
    TenantResourceUsageDetailListParams,
    TenantResourceUsageDetail,
    ResourceAdjustmentTypeEnum,
    TenantResourceUtilization,
    TenantResourceUtilizationList,
    Tenant,
)
from gpustack.schemas.load import GPULoad
from sqlmodel import select, func
from gpustack.schemas.workers import Worker
from gpustack.server.tenant_services import (
    TenantService,
    TenantResourceService,
    TenantResourceAdjustmentService,
    TenantResourceUsageDetailService,
)

router = APIRouter()


# ============ Tenant Resources Routes ============


@router.post(
    "",
    response_model=TenantResourcePublic,
    status_code=201,
    dependencies=[Depends(get_admin_user)],
)
async def create_tenant_resource(
    resource_create: TenantResourceCreate, session: SessionDep
):
    """Allocate a resource to a tenant."""
    # Verify tenant exists
    tenant_service = TenantService(session)
    tenant = await tenant_service.get_by_id(resource_create.tenant_id)
    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {resource_create.tenant_id} not found")

    # Verify worker exists
    worker = await Worker.one_by_id(session, resource_create.worker_id)
    if not worker or worker.deleted_at:
        raise NotFoundException(f"Worker with ID {resource_create.worker_id} not found")

    # Create the resource allocation
    service = TenantResourceService(session)
    resource = await service.create(resource_create)

    # Log the adjustment
    adjustment_service = TenantResourceAdjustmentService(session)
    await adjustment_service.create(
        TenantResourceAdjustmentCreate(
            tenant_id=resource_create.tenant_id,
            adjustment_type=ResourceAdjustmentTypeEnum.ADD,
            adjustment_time=datetime.now(),
            adjustment_details={
                "resource_id": resource.id,
                "worker_id": resource_create.worker_id,
                "gpu_id": resource_create.gpu_id,
            },
            reason="Resource allocation created",
        )
    )

    return resource


@router.post(
    "/batch",
    response_model=List[TenantResourcePublic],
    status_code=201,
    dependencies=[Depends(get_admin_user)],
)
async def create_tenant_resources_batch(
    resource_creates: List[TenantResourceCreate], session: SessionDep
):
    """Allocate multiple resources to a tenant."""
    if not resource_creates:
        raise BadRequestException("Empty resource list provided")

    # Verify tenant exists (use the first one as they should all be the same)
    tenant_service = TenantService(session)
    tenant_id = resource_creates[0].tenant_id
    tenant = await tenant_service.get_by_id(tenant_id)
    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    # Create the resource allocations
    service = TenantResourceService(session)
    resources = await service.create_many(resource_creates)

    # Log the adjustment
    adjustment_service = TenantResourceAdjustmentService(session)
    await adjustment_service.create(
        TenantResourceAdjustmentCreate(
            tenant_id=tenant_id,
            adjustment_type=ResourceAdjustmentTypeEnum.ADD,
            adjustment_time=datetime.now(),
            adjustment_details={
                "resource_count": len(resources),
                "resource_ids": [r.id for r in resources],
            },
            reason=f"Batch resource allocation ({len(resources)} resources)",
        )
    )

    return resources


@router.get("", response_model=TenantResourcesPublic)
async def list_tenant_resources(
    session: SessionDep,
    engine: EngineDep,
    params: TenantResourceListParams = Depends(),
    tenant_id: Optional[int] = None,
    worker_id: Optional[int] = None,
    gpu_id: Optional[str] = None,
):
    """List tenant resource allocations with optional filters."""
    fields = {"deleted_at": None}

    if tenant_id:
        fields["tenant_id"] = tenant_id
    if worker_id:
        fields["worker_id"] = worker_id
    if gpu_id:
        fields["gpu_id"] = gpu_id

    # Handle streaming mode (watch=true)
    if params.watch:
        return StreamingResponse(
            TenantResource.streaming(engine, fields=fields),
            media_type="text/event-stream",
        )

    # Get paginated tenant resources
    return await TenantResource.paginated_by_query(
        session=session,
        fields=fields,
        page=params.page,
        per_page=params.perPage,
        order_by=params.order_by,
    )


@router.get("/top-utilization", response_model=TenantResourceUtilizationList)
async def get_top_tenant_utilization(session: SessionDep):
    """Get top 5 tenants by GPU count with current utilization metrics for star chart."""
    # Step 1: Get all active tenants first
    stmt_tenants = select(Tenant).where(Tenant.deleted_at.is_(None))
    tenants_result = await session.exec(stmt_tenants)
    all_tenants = tenants_result.all()

    if not all_tenants:
        return TenantResourceUtilizationList(items=[])

    # Step 2: Get GPU count for each tenant
    stmt_tenant_gpu_count = (
        select(
            TenantResource.tenant_id, func.count(TenantResource.id).label("gpu_count")
        )
        .where(TenantResource.deleted_at.is_(None))
        .group_by(TenantResource.tenant_id)
    )

    tenant_gpu_count_result = await session.exec(stmt_tenant_gpu_count)
    tenant_gpu_count_map = {
        result.tenant_id: result.gpu_count for result in tenant_gpu_count_result.all()
    }

    # Create tenant dict with their GPU count
    tenants_dict = {
        tenant.id: {
            "tenant": tenant,
            "gpu_count": tenant_gpu_count_map.get(tenant.id, 0),
        }
        for tenant in all_tenants
    }

    # Step 3: Sort tenants by GPU count and get top 5
    sorted_tenants = sorted(
        tenants_dict.values(), key=lambda x: x["gpu_count"], reverse=True
    )[:5]

    # Get tenant_ids of top 5 tenants
    top_tenant_ids = [tenant_data["tenant"].id for tenant_data in sorted_tenants]

    # Step 4: Get GPU resources for top 5 tenants to get gpu_ids
    stmt_tenant_resources = select(TenantResource).where(
        TenantResource.tenant_id.in_(top_tenant_ids),
        TenantResource.deleted_at.is_(None),
        TenantResource.gpu_id.is_not(None),
    )

    resources_result = await session.exec(stmt_tenant_resources)
    resources = resources_result.all()

    # Group resources by tenant_id
    resources_by_tenant = {tid: [] for tid in top_tenant_ids}
    for resource in resources:
        resources_by_tenant[resource.tenant_id].append(resource)

    # Get all gpu_ids for these resources
    gpu_ids = [r.gpu_id for r in resources if r.gpu_id]

    # Step 5: Get latest GPU loads for these gpu_ids
    stmt_latest_loads = (
        select(GPULoad.gpu_id, func.max(GPULoad.timestamp).label("latest_timestamp"))
        .where(GPULoad.gpu_id.in_(gpu_ids))
        .group_by(GPULoad.gpu_id)
    )

    latest_loads_result = await session.exec(stmt_latest_loads)
    latest_loads = latest_loads_result.all()

    # Get the actual load data for these latest timestamps
    latest_load_data = {}
    if latest_loads:
        gpu_id_timestamp_pairs = [
            (ll.gpu_id, ll.latest_timestamp) for ll in latest_loads
        ]

        # Create conditions for each gpu_id and timestamp pair
        load_conditions = []
        for gpu_id, timestamp in gpu_id_timestamp_pairs:
            load_conditions.append(
                (GPULoad.gpu_id == gpu_id) & (GPULoad.timestamp == timestamp)
            )

        from sqlalchemy import or_

        stmt_gpu_loads = select(GPULoad).where(or_(*load_conditions))

        gpu_loads_result = await session.exec(stmt_gpu_loads)
        for load in gpu_loads_result.all():
            latest_load_data[load.gpu_id] = load

    # Step 6: Calculate utilization for each top tenant
    utilization_list = []
    for tenant_data in sorted_tenants:
        tenant = tenant_data["tenant"]
        tenant_id = tenant.id
        gpu_count = tenant_data["gpu_count"]

        tenant_resources = resources_by_tenant.get(tenant_id, [])

        # Calculate average GPU utilization and VRAM utilization
        gpu_utilizations = []
        vram_utilizations = []

        for resource in tenant_resources:
            if not resource.gpu_id:
                continue

            load = latest_load_data.get(resource.gpu_id)
            if load:
                if load.gpu_utilization is not None:
                    gpu_utilizations.append(load.gpu_utilization)
                if load.vram_utilization is not None:
                    vram_utilizations.append(load.vram_utilization)

        # Calculate average utilization, default to 0 if no data
        avg_gpu_util = (
            sum(gpu_utilizations) / len(gpu_utilizations) if gpu_utilizations else 0.0
        )
        avg_vram_util = (
            sum(vram_utilizations) / len(vram_utilizations)
            if vram_utilizations
            else 0.0
        )

        # Create utilization entry
        utilization = TenantResourceUtilization(
            tenant_id=tenant_id,
            tenant_name=tenant.name,
            gpu_count=gpu_count,
            gpu_utilization=avg_gpu_util,
            vram_utilization=avg_vram_util,
        )
        utilization_list.append(utilization)

    return TenantResourceUtilizationList(items=utilization_list)


@router.get("/all-utilization", response_model=TenantResourceUtilizationList)
async def get_all_tenant_utilization(session: SessionDep):
    """Get all tenants with current GPU and VRAM utilization metrics."""
    # Step 1: Get all active tenants
    stmt_tenants = select(Tenant).where(Tenant.deleted_at.is_(None))
    tenants_result = await session.exec(stmt_tenants)
    all_tenants = tenants_result.all()

    if not all_tenants:
        return TenantResourceUtilizationList(items=[])

    # Step 2: Get GPU count for each tenant
    stmt_tenant_gpu_count = (
        select(
            TenantResource.tenant_id, func.count(TenantResource.id).label("gpu_count")
        )
        .where(TenantResource.deleted_at.is_(None))
        .group_by(TenantResource.tenant_id)
    )

    tenant_gpu_count_result = await session.exec(stmt_tenant_gpu_count)
    tenant_gpu_count_map = {
        result.tenant_id: result.gpu_count for result in tenant_gpu_count_result.all()
    }

    # Create tenant dict with their GPU count
    tenants_dict = {
        tenant.id: {
            "tenant": tenant,
            "gpu_count": tenant_gpu_count_map.get(tenant.id, 0),
        }
        for tenant in all_tenants
    }

    # Step 3: Sort tenants by GPU count
    sorted_tenants = sorted(
        tenants_dict.values(), key=lambda x: x["gpu_count"], reverse=True
    )

    # Get all tenant_ids
    all_tenant_ids = [tenant_data["tenant"].id for tenant_data in sorted_tenants]

    # Step 4: Get GPU resources for all tenants to get gpu_ids
    stmt_tenant_resources = select(TenantResource).where(
        TenantResource.tenant_id.in_(all_tenant_ids),
        TenantResource.deleted_at.is_(None),
        TenantResource.gpu_id.is_not(None),
    )

    resources_result = await session.exec(stmt_tenant_resources)
    resources = resources_result.all()

    # Group resources by tenant_id
    resources_by_tenant = {tid: [] for tid in all_tenant_ids}
    for resource in resources:
        resources_by_tenant[resource.tenant_id].append(resource)

    # Get all gpu_ids for these resources
    gpu_ids = [r.gpu_id for r in resources if r.gpu_id]

    # Step 5: Get latest GPU loads for these gpu_ids
    stmt_latest_loads = (
        select(GPULoad.gpu_id, func.max(GPULoad.timestamp).label("latest_timestamp"))
        .where(GPULoad.gpu_id.in_(gpu_ids))
        .group_by(GPULoad.gpu_id)
    )

    latest_loads_result = await session.exec(stmt_latest_loads)
    latest_loads = latest_loads_result.all()

    # Get the actual load data for these latest timestamps
    latest_load_data = {}
    if latest_loads:
        gpu_id_timestamp_pairs = [
            (ll.gpu_id, ll.latest_timestamp) for ll in latest_loads
        ]

        # Create conditions for each gpu_id and timestamp pair
        load_conditions = []
        for gpu_id, timestamp in gpu_id_timestamp_pairs:
            load_conditions.append(
                (GPULoad.gpu_id == gpu_id) & (GPULoad.timestamp == timestamp)
            )

        from sqlalchemy import or_

        stmt_gpu_loads = select(GPULoad).where(or_(*load_conditions))

        gpu_loads_result = await session.exec(stmt_gpu_loads)
        for load in gpu_loads_result.all():
            latest_load_data[load.gpu_id] = load

    # Step 6: Calculate utilization for each tenant
    utilization_list = []
    for tenant_data in sorted_tenants:
        tenant = tenant_data["tenant"]
        tenant_id = tenant.id
        gpu_count = tenant_data["gpu_count"]

        tenant_resources = resources_by_tenant.get(tenant_id, [])

        # Calculate average GPU utilization and VRAM utilization
        gpu_utilizations = []
        vram_utilizations = []

        for resource in tenant_resources:
            if not resource.gpu_id:
                continue

            load = latest_load_data.get(resource.gpu_id)
            if load:
                if load.gpu_utilization is not None:
                    gpu_utilizations.append(load.gpu_utilization)
                if load.vram_utilization is not None:
                    vram_utilizations.append(load.vram_utilization)

        # Calculate average utilization, default to 0 if no data
        avg_gpu_util = (
            sum(gpu_utilizations) / len(gpu_utilizations) if gpu_utilizations else 0.0
        )
        avg_vram_util = (
            sum(vram_utilizations) / len(vram_utilizations)
            if vram_utilizations
            else 0.0
        )

        # Create utilization entry
        utilization = TenantResourceUtilization(
            tenant_id=tenant_id,
            tenant_name=tenant.name,
            gpu_count=gpu_count,
            gpu_utilization=avg_gpu_util,
            vram_utilization=avg_vram_util,
        )
        utilization_list.append(utilization)

    return TenantResourceUtilizationList(items=utilization_list)


async def _get_tenant_resources(session, tenant_id):
    """
    Get all resources for a tenant.
    """
    return await TenantResource.all_by_fields(
        session, fields={"tenant_id": tenant_id, "deleted_at": None}
    )


async def _get_workers_for_tenant(session, worker_ids):
    """
    Get all workers for a tenant based on worker IDs.
    """
    if not worker_ids:
        return []
    from gpustack.schemas import Worker

    return await Worker.all_by_fields(
        session, fields={"id": worker_ids, "deleted_at": None}
    )


async def _calculate_current_utilization(resources, workers):
    """
    Calculate current GPU and VRAM utilization for a tenant.
    """
    gpu_util = 0.0
    gpu_count = 0
    vram_total = 0
    vram_used = 0

    for worker in workers:
        if worker.status and worker.status.gpu_devices:
            for gpu in worker.status.gpu_devices:
                # Check if GPU is assigned to tenant
                if any(
                    r.gpu_id and r.gpu_id.endswith(f":{gpu.index}") for r in resources
                ):
                    if gpu.core and gpu.core.utilization_rate is not None:
                        gpu_util += gpu.core.utilization_rate
                        gpu_count += 1
                    if gpu.memory:
                        vram_total += gpu.memory.total
                        if gpu.memory.utilization_rate is not None:
                            vram_used += gpu.memory.total * (
                                gpu.memory.utilization_rate / 100
                            )

    gpu_utilization = gpu_util / gpu_count if gpu_count > 0 else 0.0
    vram_utilization = vram_used / vram_total * 100 if vram_total > 0 else 0.0

    return gpu_utilization, vram_total, vram_used, vram_utilization


async def _get_historical_load(session, gpu_ids, time_dimension):
    """
    Get historical GPU and VRAM load data based on time dimension.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text
    from gpustack.schemas.dashboard import TimeSeriesData

    now = datetime.now(timezone.utc)
    if time_dimension == "today":
        start_time = now - timedelta(days=1)
    elif time_dimension == "week":
        start_time = now - timedelta(days=7)
    elif time_dimension == "month":
        start_time = now - timedelta(days=30)
    else:
        start_time = now - timedelta(days=1)

    gpu_history = []
    vram_history = []

    if gpu_ids:
        # Convert start_time to Unix timestamp for comparison with GPULoad.timestamp (integer)
        start_timestamp = int(start_time.timestamp())

        stmt = text(
            """
        SELECT
            gpu_id,
            date_trunc('hour', to_timestamp(timestamp)) AS hour,
            AVG(gpu_utilization) AS avg_gpu,
            AVG(vram_utilization) AS avg_vram
        FROM gpu_loads
        WHERE
            gpu_id = ANY(:gpu_ids) AND
            timestamp >= :start_timestamp
        GROUP BY
            gpu_id,
            date_trunc('hour', to_timestamp(timestamp))
        ORDER BY
            date_trunc('hour', to_timestamp(timestamp))
        """
        )

        # Use text() query with explicit parameters to avoid ORM issues
        results = await session.exec(
            stmt, params={"gpu_ids": gpu_ids, "start_timestamp": start_timestamp}
        )

        # Aggregate by hour across all GPUs
        hourly_data = {}
        for result in results:
            hour_key = result.hour
            if hour_key not in hourly_data:
                hourly_data[hour_key] = {"gpu_sum": 0, "vram_sum": 0, "count": 0}

            if result.avg_gpu is not None:
                hourly_data[hour_key]["gpu_sum"] += result.avg_gpu
            if result.avg_vram is not None:
                hourly_data[hour_key]["vram_sum"] += result.avg_vram
            hourly_data[hour_key]["count"] += 1

        # Create time series data
        for hour, data in sorted(hourly_data.items()):
            if data["count"] > 0:
                gpu_history.append(
                    TimeSeriesData(
                        timestamp=int(hour.timestamp()),
                        value=data["gpu_sum"] / data["count"],
                    )
                )
                vram_history.append(
                    TimeSeriesData(
                        timestamp=int(hour.timestamp()),
                        value=data["vram_sum"] / data["count"],
                    )
                )

    return gpu_history, vram_history


@router.get("/stats")
async def get_tenant_resource_stats(
    session: SessionDep,
    current_user: CurrentUserDep,
    tenant_id: Optional[int] = None,
    time_dimension: Optional[str] = "today",  # today, week, month
):
    """
    Get tenant resource statistics and system load.
    """
    from gpustack.schemas.tenants import (
        TenantResourceStats,
        TenantResourceCounts,
        TenantSystemLoad,
    )

    # Step 1: Get all resources for the tenant
    if not tenant_id:
        tenant_id = current_user.tenant_id
    resources = await _get_tenant_resources(session, tenant_id)

    # Get all GPU IDs and worker IDs for this tenant
    gpu_ids = [r.gpu_id for r in resources if r.gpu_id]
    worker_ids = [r.worker_id for r in resources]

    # Step 2: Get workers and calculate utilization
    workers = await _get_workers_for_tenant(session, worker_ids)
    util_results = await _calculate_current_utilization(resources, workers)
    gpu_utilization, vram_total, vram_used, vram_utilization = util_results

    # Step 3: Get historical system load
    gpu_history, vram_history = await _get_historical_load(
        session, gpu_ids, time_dimension
    )

    # Step 4: Prepare resource counts
    resource_counts = TenantResourceCounts(
        gpu_total=len(resources),
        gpu_used=len(resources),
        gpu_utilization=gpu_utilization,
        vram_total=vram_total,
        vram_used=int(vram_used),
        vram_utilization=vram_utilization,
    )

    # Step 5: Prepare system load
    system_load = TenantSystemLoad(
        current={
            "gpu_utilization": gpu_utilization,
            "vram_utilization": vram_utilization,
        },
        history={"gpu": gpu_history, "vram": vram_history},
    )

    # Return combined stats
    return TenantResourceStats(resource_counts=resource_counts, system_load=system_load)


@router.get("/{resource_id}", response_model=TenantResourcePublic)
async def get_tenant_resource(resource_id: int, session: SessionDep):
    """Get a tenant resource allocation by ID."""
    service = TenantResourceService(session)
    resource = await service.get_by_id(resource_id)

    if not resource or resource.deleted_at:
        raise NotFoundException(f"Tenant resource with ID {resource_id} not found")

    return resource


@router.put(
    "/{resource_id}",
    response_model=TenantResourcePublic,
    dependencies=[Depends(get_admin_user)],
)
async def update_tenant_resource(
    resource_id: int, resource_update: TenantResourceUpdate, session: SessionDep
):
    """Update a tenant resource allocation."""
    service = TenantResourceService(session)
    resource = await service.get_by_id(resource_id)

    if not resource or resource.deleted_at:
        raise NotFoundException(f"Tenant resource with ID {resource_id} not found")

    # Update the resource
    updated_resource = await service.update(resource_id, resource_update)

    # Log the adjustment
    adjustment_service = TenantResourceAdjustmentService(session)
    await adjustment_service.create(
        TenantResourceAdjustmentCreate(
            tenant_id=resource.tenant_id,
            adjustment_type=ResourceAdjustmentTypeEnum.REPLACE,
            adjustment_time=datetime.now(),
            adjustment_details={
                "resource_id": resource_id,
                "updates": resource_update.model_dump(exclude_unset=True),
            },
            reason="Resource allocation updated",
        )
    )

    return updated_resource


@router.delete(
    "/{resource_id}", status_code=204, dependencies=[Depends(get_admin_user)]
)
async def delete_tenant_resource(resource_id: int, session: SessionDep):
    """Delete a tenant resource allocation (soft delete)."""
    service = TenantResourceService(session)
    resource = await service.get_by_id(resource_id)

    if not resource or resource.deleted_at:
        raise NotFoundException(f"Tenant resource with ID {resource_id} not found")

    # Log the adjustment before deletion
    adjustment_service = TenantResourceAdjustmentService(session)
    await adjustment_service.create(
        TenantResourceAdjustmentCreate(
            tenant_id=resource.tenant_id,
            adjustment_type=ResourceAdjustmentTypeEnum.REMOVE,
            adjustment_time=datetime.now(),
            adjustment_details={
                "resource_id": resource_id,
                "worker_id": resource.worker_id,
                "gpu_id": resource.gpu_id,
            },
            reason="Resource allocation removed",
        )
    )

    await service.delete(resource_id)


# ============ Tenant Resource Adjustments Routes ============


@router.get("/adjustments", response_model=TenantResourceAdjustmentsPublic)
async def list_tenant_resource_adjustments(
    session: SessionDep,
    engine: EngineDep,
    params: TenantResourceAdjustmentListParams = Depends(),
    tenant_id: Optional[int] = None,
    adjustment_type: Optional[ResourceAdjustmentTypeEnum] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
):
    """List tenant resource adjustment records with optional filters."""
    fields = {"deleted_at": None}

    if tenant_id:
        fields["tenant_id"] = tenant_id
    if adjustment_type:
        fields["adjustment_type"] = adjustment_type

    # Handle streaming mode (watch=true)
    if params.watch:
        return StreamingResponse(
            TenantResourceAdjustment.streaming(engine, fields=fields),
            media_type="text/event-stream",
        )

    # Get paginated adjustments
    return await TenantResourceAdjustment.paginated_by_query(
        session=session,
        fields=fields,
        page=params.page,
        per_page=params.perPage,
        order_by=params.order_by,
    )


@router.get(
    "/adjustments/{adjustment_id}",
    response_model=TenantResourceAdjustmentPublic,
)
async def get_tenant_resource_adjustment(adjustment_id: int, session: SessionDep):
    """Get a tenant resource adjustment record by ID."""
    service = TenantResourceAdjustmentService(session)
    adjustment = await service.get_by_id(adjustment_id)

    if not adjustment or adjustment.deleted_at:
        raise NotFoundException(
            f"Tenant resource adjustment with ID {adjustment_id} not found"
        )

    return adjustment


# ============ Tenant Resource Usage Details Routes ============


@router.post(
    "/usage",
    response_model=TenantResourceUsageDetailPublic,
    status_code=201,
    dependencies=[Depends(get_admin_user)],
)
async def create_tenant_usage_detail(
    usage_create: TenantResourceUsageDetailCreate, session: SessionDep
):
    """Create a tenant resource usage detail record."""
    # Verify tenant exists
    tenant_service = TenantService(session)
    tenant = await tenant_service.get_by_id(usage_create.tenant_id)
    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {usage_create.tenant_id} not found")

    # Create or update the usage detail
    service = TenantResourceUsageDetailService(session)
    usage = await service.upsert_usage_detail(usage_create)
    return usage


@router.post(
    "/usage/batch",
    response_model=List[TenantResourceUsageDetailPublic],
    status_code=201,
    dependencies=[Depends(get_admin_user)],
)
async def create_tenant_usage_details_batch(
    usage_creates: List[TenantResourceUsageDetailCreate], session: SessionDep
):
    """Create multiple tenant resource usage detail records."""
    if not usage_creates:
        raise BadRequestException("Empty usage detail list provided")

    service = TenantResourceUsageDetailService(session)
    usages = await service.create_many(usage_creates)
    return usages


@router.get("/usage", response_model=TenantResourceUsageDetailsPublic)
async def list_tenant_usage_details(
    session: SessionDep,
    engine: EngineDep,
    params: TenantResourceUsageDetailListParams = Depends(),
    tenant_id: Optional[int] = None,
    worker_id: Optional[int] = None,
    gpu_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):
    """List tenant resource usage details with optional filters."""
    fields = {"deleted_at": None}

    if tenant_id:
        fields["tenant_id"] = tenant_id
    if worker_id:
        fields["worker_id"] = worker_id
    if gpu_id:
        fields["gpu_id"] = gpu_id

    # Handle streaming mode (watch=true)
    if params.watch:
        return StreamingResponse(
            TenantResourceUsageDetail.streaming(engine, fields=fields),
            media_type="text/event-stream",
        )

    # Get paginated usage details
    return await TenantResourceUsageDetail.paginated_by_query(
        session=session,
        fields=fields,
        page=params.page,
        per_page=params.perPage,
        order_by=params.order_by,
    )


@router.get("/usage/{usage_id}", response_model=TenantResourceUsageDetailPublic)
async def get_tenant_usage_detail(usage_id: int, session: SessionDep):
    """Get a tenant resource usage detail by ID."""
    service = TenantResourceUsageDetailService(session)
    usage = await service.get_by_id(usage_id)

    if not usage or usage.deleted_at:
        raise NotFoundException(
            f"Tenant resource usage detail with ID {usage_id} not found"
        )

    return usage
