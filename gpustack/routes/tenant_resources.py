from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from gpustack.api.exceptions import (
    NotFoundException,
    BadRequestException,
)
from gpustack.server.deps import SessionDep, EngineDep, get_admin_user
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
    # Step 1: Get top 5 tenants by GPU count
    stmt_tenant_gpu_count = (
        select(
            TenantResource.tenant_id, func.count(TenantResource.id).label("gpu_count")
        )
        .where(TenantResource.deleted_at.is_(None))
        .group_by(TenantResource.tenant_id)
        .order_by(func.count(TenantResource.id).desc())
        .limit(5)
    )

    top_tenants_result = await session.exec(stmt_tenant_gpu_count)
    top_tenants = top_tenants_result.all()

    if not top_tenants:
        return TenantResourceUtilizationList(items=[])

    # Step 2: Get tenant details for these top tenants
    tenant_ids = [tt.tenant_id for tt in top_tenants]
    stmt_tenants = select(Tenant).where(
        Tenant.id.in_(tenant_ids), Tenant.deleted_at.is_(None)
    )

    tenants_result = await session.exec(stmt_tenants)
    tenants = {t.id: t for t in tenants_result.all()}

    # Step 3: Get GPU resources for these tenants to get gpu_ids
    stmt_tenant_resources = select(TenantResource).where(
        TenantResource.tenant_id.in_(tenant_ids),
        TenantResource.deleted_at.is_(None),
        TenantResource.gpu_id.is_not(None),
    )

    resources_result = await session.exec(stmt_tenant_resources)
    resources = resources_result.all()

    # Group resources by tenant_id
    resources_by_tenant = {tid: [] for tid in tenant_ids}
    for resource in resources:
        resources_by_tenant[resource.tenant_id].append(resource)

    # Get all gpu_ids for these resources
    gpu_ids = [r.gpu_id for r in resources if r.gpu_id]

    # Step 4: Get latest GPU loads for these gpu_ids
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

    # Step 5: Calculate utilization for each tenant
    utilization_list = []
    for tt in top_tenants:
        tenant_id = tt.tenant_id
        gpu_count = tt.gpu_count

        tenant = tenants.get(tenant_id)
        if not tenant:
            continue

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

        # Calculate average utilization
        avg_gpu_util = None
        avg_vram_util = None

        if gpu_utilizations:
            avg_gpu_util = sum(gpu_utilizations) / len(gpu_utilizations)

        if vram_utilizations:
            avg_vram_util = sum(vram_utilizations) / len(vram_utilizations)

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
