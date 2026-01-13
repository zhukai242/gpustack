from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import select

from gpustack.api.exceptions import (
    AlreadyExistsException,
    NotFoundException,
    BadRequestException,
)
from gpustack.server.deps import SessionDep, EngineDep, get_admin_user
from gpustack.schemas.tenants import (
    TenantCreate,
    TenantUpdate,
    TenantPublic,
    TenantsPublic,
    TenantListParams,
    Tenant,
    TenantStatusEnum,
    TenantWithResources,
    TenantResourceCreate,
    ResourceAdjustmentTypeEnum,
    TenantResourceAdjustmentCreate,
)
from gpustack.schemas.workers import Worker
from gpustack.schemas.licenses import LicenseActivation, LicenseStatusEnum
from gpustack.server.tenant_services import (
    TenantService,
    TenantResourceService,
    TenantResourceAdjustmentService,
)

router = APIRouter()

# ============ Models for Available Resources ============


class ResourceAllocationItem(BaseModel):
    """Resource allocation item for tenant creation."""

    worker_id: int
    gpu_id: str  # Format: worker_name:gpu_type:gpu_index
    resource_config: Optional[Dict[str, Any]] = Field(default_factory=dict)


class TenantCreateWithResources(BaseModel):
    """Create a tenant with initial resource allocations."""

    # Basic tenant info
    name: str
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    resource_start_time: Optional[datetime] = None  # Resource activation start time
    resource_end_time: Optional[datetime] = None  # Expected resource expiration time
    status: TenantStatusEnum = (
        TenantStatusEnum.ACTIVE
    )  # Default: ACTIVE (allocated but not activated)
    description: Optional[str] = None
    labels: Optional[Dict[str, str]] = Field(default_factory=dict)

    # Resource allocations
    resources: List[ResourceAllocationItem] = Field(default_factory=list)
    operator: Optional[str] = None  # Who created this tenant


class TenantResourceExpansion(BaseModel):
    """Expand tenant resources."""

    resources: List[ResourceAllocationItem] = Field(
        ..., description="List of resources to add"
    )
    operator: Optional[str] = None
    reason: Optional[str] = None


class TenantResourceReduction(BaseModel):
    """Reduce tenant resources."""

    gpu_ids: List[str] = Field(
        ...,
        description="List of GPU IDs to remove (format: worker_name:gpu_type:gpu_index)",
    )
    operator: Optional[str] = None
    reason: Optional[str] = None


class TenantResourceActivation(BaseModel):
    """Activate tenant resources to start using."""

    gpu_ids: Optional[List[str]] = Field(
        default=None,
        description="List of GPU IDs to activate. If empty, activate all allocated resources.",
    )
    resource_start_time: Optional[datetime] = Field(
        default=None,
        description="Resource activation start time. If not provided, use current time.",
    )
    operator: Optional[str] = None
    reason: Optional[str] = None


class AvailableGPUInfo(BaseModel):
    """Available GPU information for tenant allocation."""

    gpu_id: str  # Format: worker_name:gpu_type:gpu_index
    gpu_index: int
    gpu_name: str
    gpu_type: Optional[str] = None
    gpu_vendor: Optional[str] = None
    memory_total_gb: Optional[float] = None
    memory_available_gb: Optional[float] = None
    is_allocated: bool = False  # Whether already allocated to a tenant
    tenant_id: Optional[int] = None  # If allocated, which tenant
    tenant_name: Optional[str] = None  # If allocated, tenant name


class AvailableWorkerInfo(BaseModel):
    """Available worker information for tenant allocation."""

    worker_id: int
    worker_name: str
    worker_ip: str
    worker_state: Optional[str] = None
    cluster_id: int
    cluster_name: Optional[str] = None
    rack_id: Optional[int] = None
    rack_name: Optional[str] = None
    total_gpus: int = 0
    available_gpus: int = 0
    allocated_gpus: int = 0
    gpu_devices: List[AvailableGPUInfo] = Field(default_factory=list)


class AvailableResourcesResponse(BaseModel):
    """Response containing all available workers and GPUs."""

    workers: List[AvailableWorkerInfo] = Field(default_factory=list)
    total_workers: int = 0
    total_gpus: int = 0
    available_gpus: int = 0
    allocated_gpus: int = 0


# ============ Tenant Routes ============


async def _build_worker_filters(
    cluster_id: Optional[int], rack_id: Optional[int]
) -> dict:
    """
    Build worker query filters based on cluster_id and rack_id.
    """
    fields = {"deleted_at": None}
    if cluster_id:
        fields["cluster_id"] = cluster_id
    if rack_id:
        fields["rack_id"] = rack_id
    return fields


async def _build_allocated_gpu_map(
    session: SessionDep,
    resource_service: TenantResourceService,
    tenant_service: TenantService,
) -> dict:
    """
    Build a map of allocated GPU IDs to tenant info.
    """
    all_allocated_resources = await resource_service.get_active_resources()
    allocated_gpu_map = {}  # gpu_id -> (tenant_id, tenant_name)

    for resource in all_allocated_resources:
        if resource.gpu_id:
            tenant = await tenant_service.get_by_id(resource.tenant_id)
            tenant_name = tenant.name if tenant else "Unknown"
            allocated_gpu_map[resource.gpu_id] = (resource.tenant_id, tenant_name)

    return allocated_gpu_map


async def _build_activated_gpu_set(session: SessionDep) -> set:
    """
    Build a set of GPU IDs that are activated in license_activations.
    """
    active_activations = await session.exec(
        select(LicenseActivation).where(
            LicenseActivation.status == LicenseStatusEnum.ACTIVE
        )
    )

    activated_gpu_ids = set()
    for activation in active_activations:
        if activation.gpu_id:
            activated_gpu_ids.add(activation.gpu_id)

    return activated_gpu_ids


async def _process_gpu_device(
    gpu, worker, allocated_gpu_map, activated_gpu_ids, include_allocated
):
    """
    Process a single GPU device and return GPU info if it should be included.
    """
    # Generate GPU ID (format: worker_name:gpu_type:gpu_index)
    gpu_type = gpu.type if gpu.type else "unknown"
    gpu_id = f"{worker.name}:{gpu_type}:{gpu.index}"

    # Check if this GPU is activated
    is_activated = gpu_id in activated_gpu_ids
    if not is_activated:
        return None, False, False

    # Check if this GPU is allocated
    is_allocated = gpu_id in allocated_gpu_map
    tenant_id = None
    tenant_name = None
    if is_allocated:
        tenant_id, tenant_name = allocated_gpu_map[gpu_id]

    # Skip allocated GPUs if not requested
    if not include_allocated and is_allocated:
        return None, is_allocated, True

    # Calculate memory info
    memory_total_gb = None
    memory_available_gb = None
    if gpu.memory and gpu.memory.total:
        memory_total_gb = round(gpu.memory.total / (1024**3), 2)
        if gpu.memory.used:
            memory_used_gb = gpu.memory.used / (1024**3)
            memory_available_gb = round(memory_total_gb - memory_used_gb, 2)
        else:
            memory_available_gb = memory_total_gb

    # Create GPU info
    gpu_info = AvailableGPUInfo(
        gpu_id=gpu_id,
        gpu_index=gpu.index,
        gpu_name=gpu.name or "Unknown GPU",
        gpu_type=gpu.type,
        gpu_vendor=gpu.vendor,
        memory_total_gb=memory_total_gb,
        memory_available_gb=memory_available_gb,
        is_allocated=is_allocated,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
    )

    return gpu_info, is_allocated, False


async def _process_worker(
    worker, allocated_gpu_map, activated_gpu_ids, include_allocated
):
    """
    Process a single worker and return worker info with GPU devices.
    """
    gpu_devices_list = []
    worker_total_gpus = 0
    worker_available_gpus = 0
    worker_allocated_gpus = 0

    # Extract GPU devices from worker status
    if (
        worker.status
        and hasattr(worker.status, "gpu_devices")
        and worker.status.gpu_devices
    ):
        for gpu in worker.status.gpu_devices:
            gpu_info, is_allocated, skipped = await _process_gpu_device(
                gpu, worker, allocated_gpu_map, activated_gpu_ids, include_allocated
            )

            if gpu_info:
                gpu_devices_list.append(gpu_info)

            if is_allocated:
                worker_allocated_gpus += 1
            else:
                worker_available_gpus += 1

        worker_total_gpus = len(worker.status.gpu_devices)

    # Get cluster and rack names
    cluster_name = None
    rack_name = None
    if worker.cluster:
        cluster_name = worker.cluster.name
    if worker.rack:
        rack_name = worker.rack.name

    # Create worker info
    worker_info = AvailableWorkerInfo(
        worker_id=worker.id,
        worker_name=worker.name,
        worker_ip=worker.ip,
        worker_state=worker.state.value if worker.state else None,
        cluster_id=worker.cluster_id,
        cluster_name=cluster_name,
        rack_id=worker.rack_id,
        rack_name=rack_name,
        total_gpus=worker_total_gpus,
        available_gpus=worker_available_gpus,
        allocated_gpus=worker_allocated_gpus,
        gpu_devices=gpu_devices_list,
    )

    return worker_info, worker_total_gpus, worker_available_gpus, worker_allocated_gpus


@router.get("/available-resources", response_model=AvailableResourcesResponse)
async def get_available_resources(
    session: SessionDep,
    cluster_id: Optional[int] = None,
    rack_id: Optional[int] = None,
    include_allocated: bool = False,
):
    """
    Get all available workers and GPUs for tenant resource allocation.

    This endpoint provides a comprehensive view of all workers and their GPU devices.
    By default, only shows unallocated GPUs to prevent double allocation.

    Query Parameters:
        - cluster_id: Filter by cluster ID
        - rack_id: Filter by rack ID
        - include_allocated: Include GPUs that are already allocated to tenants (default: False)

    Returns:
        A list of workers with their GPU devices and allocation status.
        Only unallocated GPUs are returned by default.
    """
    # Build worker filters
    worker_filters = await _build_worker_filters(cluster_id, rack_id)

    # Get all workers
    workers = await Worker.all_by_fields(session, fields=worker_filters)

    # Initialize services
    resource_service = TenantResourceService(session)
    tenant_service = TenantService(session)

    # Build supporting data structures
    allocated_gpu_map = await _build_allocated_gpu_map(
        session, resource_service, tenant_service
    )
    activated_gpu_ids = await _build_activated_gpu_set(session)

    # Build response
    result_workers = []
    total_gpus_count = 0
    available_gpus_count = 0
    allocated_gpus_count = 0

    for worker in workers:
        worker_info, worker_total, worker_available, worker_allocated = (
            await _process_worker(
                worker, allocated_gpu_map, activated_gpu_ids, include_allocated
            )
        )

        result_workers.append(worker_info)
        total_gpus_count += worker_total
        available_gpus_count += worker_available
        allocated_gpus_count += worker_allocated

    return AvailableResourcesResponse(
        workers=result_workers,
        total_workers=len(result_workers),
        total_gpus=total_gpus_count,
        available_gpus=available_gpus_count,
        allocated_gpus=allocated_gpus_count,
    )


@router.post(
    "",
    response_model=TenantPublic,
    status_code=201,
    dependencies=[Depends(get_admin_user)],
)
async def create_tenant(tenant_create: TenantCreateWithResources, session: SessionDep):
    """
    Create a new tenant with optional resource allocations.

    This endpoint creates a tenant with status ACTIVE (allocated but not activated).
    Resources are allocated but not started. Use the activate-resources endpoint
    to start using the resources, which will:
    - Set tenant status to INUSE
    - Set resource_start_time
    - Start generating usage_details via scheduled tasks

    All resource allocations will be recorded in the adjustment history.
    """
    # Check if tenant with the same name already exists
    tenant_service = TenantService(session)
    existing_tenant = await tenant_service.get_by_name(tenant_create.name)

    if existing_tenant and not existing_tenant.deleted_at:
        raise AlreadyExistsException(f"Tenant '{tenant_create.name}' already exists")

    # Set resource_start_time to current time if resources are provided
    # and no start time is specified
    resource_start_time = tenant_create.resource_start_time
    if tenant_create.resources and not resource_start_time:
        resource_start_time = datetime.now()

    # Remove timezone info from datetime fields to match database TIMESTAMP WITHOUT TIME ZONE
    if resource_start_time and resource_start_time.tzinfo is not None:
        resource_start_time = resource_start_time.replace(tzinfo=None)

    resource_end_time = tenant_create.resource_end_time
    if resource_end_time and resource_end_time.tzinfo is not None:
        resource_end_time = resource_end_time.replace(tzinfo=None)

    # Create the tenant with provided resource_start_time if set
    tenant_data = TenantCreate(
        name=tenant_create.name,
        contact_person=tenant_create.contact_person,
        contact_phone=tenant_create.contact_phone,
        contact_email=tenant_create.contact_email,
        resource_start_time=resource_start_time,  # Set provided start time if available
        resource_end_time=resource_end_time,
        status=(
            TenantStatusEnum.ACTIVE
            if not resource_start_time
            else TenantStatusEnum.INUSE
        ),  # Set to INUSE if start time is provided
        description=tenant_create.description,
        labels=tenant_create.labels or {},
    )
    tenant = await tenant_service.create(tenant_data)

    # Allocate resources if provided
    if tenant_create.resources:
        resource_service = TenantResourceService(session)
        adjustment_service = TenantResourceAdjustmentService(session)

        allocated_resources = []
        for resource_item in tenant_create.resources:
            # Verify worker exists
            worker = await Worker.one_by_id(session, resource_item.worker_id)
            if not worker or worker.deleted_at:
                raise NotFoundException(
                    f"Worker with ID {resource_item.worker_id} not found"
                )

            # Create resource allocation with provided start time if set
            resource_create = TenantResourceCreate(
                tenant_id=tenant.id,
                worker_id=resource_item.worker_id,
                gpu_id=resource_item.gpu_id,
                resource_start_time=resource_start_time,  # Use provided start time if available
                resource_end_time=resource_end_time,
                resource_config=resource_item.resource_config,
            )
            allocated_resource = await resource_service.create(resource_create)
            allocated_resources.append(
                {
                    "resource_id": allocated_resource.id,
                    "worker_id": resource_item.worker_id,
                    "gpu_id": resource_item.gpu_id,
                }
            )

        # Record the initial resource allocation in adjustment history
        await adjustment_service.create(
            TenantResourceAdjustmentCreate(
                tenant_id=tenant.id,
                adjustment_type=ResourceAdjustmentTypeEnum.ADD,
                adjustment_time=datetime.now(),
                operator=tenant_create.operator or "system",
                adjustment_details={
                    "action": "initial_allocation",
                    "resource_count": len(allocated_resources),
                    "resources": allocated_resources,
                },
                reason="Initial resource allocation during tenant creation",
            )
        )

    # Commit the transaction first
    await session.commit()

    # Refresh the tenant object after commit to reload attributes
    await session.refresh(tenant)

    return tenant


@router.get("", response_model=TenantsPublic)
async def list_tenants(
    session: SessionDep,
    engine: EngineDep,
    params: TenantListParams = Depends(),
    name: Optional[str] = None,
    status: Optional[TenantStatusEnum] = None,
    search: Optional[str] = None,
):
    """List all tenants with optional filters."""
    fields = {"deleted_at": None}
    fuzzy_fields = {}

    if name:
        fields["name"] = name
    if status:
        fields["status"] = status
    if search:
        fuzzy_fields["name"] = search

    # Handle streaming mode (watch=true)
    if params.watch:
        return StreamingResponse(
            Tenant.streaming(engine, fields=fields, fuzzy_fields=fuzzy_fields),
            media_type="text/event-stream",
        )

    # Get paginated tenants
    return await Tenant.paginated_by_query(
        session=session,
        fields=fields,
        fuzzy_fields=fuzzy_fields,
        page=params.page,
        per_page=params.perPage,
        order_by=params.order_by,
    )


async def _get_gpu_loads(session, gpu_ids, twenty_four_hours_ago_ts):
    """Get GPU loads for the last 24 hours for all GPU IDs."""
    from sqlmodel import select
    from gpustack.schemas.load import GPULoad

    stmt_gpu_loads = select(GPULoad).where(
        GPULoad.gpu_id.in_(gpu_ids), GPULoad.timestamp >= twenty_four_hours_ago_ts
    )
    all_gpu_loads = await session.exec(stmt_gpu_loads)
    all_gpu_loads = all_gpu_loads.all()

    # Group GPU loads by GPU ID
    gpu_loads_by_gpu_id = {}
    for load in all_gpu_loads:
        if load.gpu_id not in gpu_loads_by_gpu_id:
            gpu_loads_by_gpu_id[load.gpu_id] = []
        gpu_loads_by_gpu_id[load.gpu_id].append(load)

    # Sort GPU loads by timestamp
    for gpu_id in gpu_loads_by_gpu_id:
        gpu_loads_by_gpu_id[gpu_id].sort(key=lambda x: x.timestamp)

    return gpu_loads_by_gpu_id


async def _get_workers(session, worker_ids):
    """Get workers information."""
    from sqlmodel import select
    from gpustack.schemas.workers import Worker

    stmt_workers = select(Worker).where(Worker.id.in_(worker_ids))
    workers = await session.exec(stmt_workers)
    return {w.id: w for w in workers.all()}


def _process_gpu_details(resource, worker, gpu_loads, now):
    """Process GPU details from resource and load data."""
    # Extract GPU type and index from GPU ID (format: worker_name:gpu_type:gpu_index)
    gpu_type = "Unknown"
    gpu_index = 0
    gpu_id_parts = resource.gpu_id.split(':')
    if len(gpu_id_parts) == 3:
        gpu_type = gpu_id_parts[1]
        try:
            gpu_index = int(gpu_id_parts[2])
        except ValueError:
            gpu_index = 0

    # Calculate usage trend for the last 24 hours
    usage_trend = []
    for load in gpu_loads:
        usage_trend.append(
            {
                'timestamp': load.timestamp,
                'gpu_utilization': load.gpu_utilization,
                'vram_utilization': load.vram_utilization,
            }
        )

    # Get current GPU and VRAM utilization (latest load)
    current_gpu_util = None
    current_vram_util = None
    if gpu_loads:
        latest_load = gpu_loads[-1]
        current_gpu_util = latest_load.gpu_utilization
        current_vram_util = latest_load.vram_utilization

    # Calculate cumulative usage time in hours
    cumulative_time = 0.0
    if resource.resource_start_time:
        end_time = resource.resource_end_time or now
        duration = end_time - resource.resource_start_time
        cumulative_time = duration.total_seconds() / 3600

    # Create GPU detail with all required information
    gpu_detail = {
        'gpu_id': resource.gpu_id,
        'worker_id': resource.worker_id,
        'gpu_index': gpu_index,
        'worker_name': worker.name,
        'gpu_type': gpu_type,
        'resource_start_time': resource.resource_start_time,
        'resource_end_time': resource.resource_end_time,
        'cumulative_usage_time': cumulative_time,
        'gpu_utilization': current_gpu_util,
        'vram_utilization': current_vram_util,
        'usage_trend': usage_trend,
    }

    # Create resource detail
    resource_detail = {
        'resource_id': resource.id,
        'worker_id': resource.worker_id,
        'gpu_id': resource.gpu_id,
        'gpu_type': gpu_type,
        'resource_start_time': resource.resource_start_time,
        'resource_end_time': resource.resource_end_time,
        'cumulative_usage_time': cumulative_time,
        'current_gpu_utilization': current_gpu_util,
        'current_vram_utilization': current_vram_util,
        'usage_trend': usage_trend,
    }

    return gpu_detail, resource_detail


@router.get("/{tenant_id}", response_model=TenantPublic)
async def get_tenant(tenant_id: int, session: SessionDep):
    """Get a tenant by ID with GPU and node details."""
    from datetime import datetime, timedelta, timezone
    from sqlmodel import select
    from gpustack.schemas.tenants import TenantResource

    service = TenantService(session)
    tenant = await service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    # Initialize response data
    tenant_data = tenant.model_dump()
    tenant_data['gpu_details'] = []
    tenant_data['node_details'] = []
    tenant_data['resource_details'] = []

    # Get tenant resources
    stmt_tenant_resources = select(TenantResource).where(
        TenantResource.tenant_id == tenant_id
    )
    tenant_resources = await session.exec(stmt_tenant_resources)
    tenant_resources = tenant_resources.all()

    if not tenant_resources:
        return TenantPublic(**tenant_data)

    # Get current time and 24 hours ago
    now = datetime.now(timezone.utc)
    twenty_four_hours_ago = now - timedelta(hours=24)
    twenty_four_hours_ago_ts = int(twenty_four_hours_ago.timestamp())

    # Get all worker IDs from tenant resources
    worker_ids = [res.worker_id for res in tenant_resources if res.worker_id]

    if not worker_ids:
        return TenantPublic(**tenant_data)

    # Get workers information
    workers = await _get_workers(session, worker_ids)

    # Get all GPU IDs from tenant resources
    gpu_ids = [res.gpu_id for res in tenant_resources if res.gpu_id]

    if not gpu_ids:
        return TenantPublic(**tenant_data)

    # Get GPU loads for the last 24 hours for all GPU IDs
    gpu_loads_by_gpu_id = await _get_gpu_loads(
        session, gpu_ids, twenty_four_hours_ago_ts
    )

    # Process each tenant resource to get GPU details
    worker_gpus_map = {}
    gpu_details_map = {}

    for resource in tenant_resources:
        if not resource.gpu_id:
            continue

        worker_id = resource.worker_id
        worker = workers.get(worker_id)
        if not worker:
            continue

        # Get GPU loads for this GPU ID
        gpu_loads = gpu_loads_by_gpu_id.get(resource.gpu_id, [])

        # Process GPU details
        gpu_detail, resource_detail = _process_gpu_details(
            resource, worker, gpu_loads, now
        )

        # Add to maps
        gpu_details_map[resource.gpu_id] = gpu_detail
        tenant_data['resource_details'].append(resource_detail)

        # Group GPUs by worker
        if worker_id not in worker_gpus_map:
            worker_gpus_map[worker_id] = []
        worker_gpus_map[worker_id].append(gpu_detail)

    # Create node details
    for worker_id, gpus in worker_gpus_map.items():
        worker = workers.get(worker_id)
        if not worker:
            continue

        node_detail = {
            'worker_id': worker_id,
            'worker_name': worker.name,
            'gpus': gpus,
            'total_gpus': len(gpus),
            'active_gpus': len(
                [gpu for gpu in gpus if gpu['gpu_utilization'] is not None]
            ),
        }
        tenant_data['node_details'].append(node_detail)

    # Add GPU details to response
    tenant_data['gpu_details'] = list(gpu_details_map.values())

    return TenantPublic(**tenant_data)


@router.get("/{tenant_id}/with-resources", response_model=TenantWithResources)
async def get_tenant_with_resources(tenant_id: int, session: SessionDep):
    """Get a tenant with its allocated resources."""
    tenant_service = TenantService(session)
    tenant = await tenant_service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    # Get tenant resources
    resource_service = TenantResourceService(session)
    resources = await resource_service.get_by_tenant_id(tenant_id)

    # Count unique workers and GPUs
    worker_ids = set()
    gpu_count = 0

    for resource in resources:
        worker_ids.add(resource.worker_id)
        if resource.gpu_id:
            gpu_count += 1

    return TenantWithResources(
        id=tenant.id,
        name=tenant.name,
        status=tenant.status,
        contact_person=tenant.contact_person,
        contact_email=tenant.contact_email,
        resource_start_time=tenant.resource_start_time,
        resource_end_time=tenant.resource_end_time,
        resources=resources,
        total_workers=len(worker_ids),
        total_gpus=gpu_count,
    )


@router.put(
    "/{tenant_id}",
    response_model=TenantPublic,
    dependencies=[Depends(get_admin_user)],
)
async def update_tenant(
    tenant_id: int, tenant_update: TenantUpdate, session: SessionDep
):
    """Update a tenant."""
    service = TenantService(session)
    tenant = await service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    # Check if updated name already exists
    if tenant_update.name and tenant_update.name != tenant.name:
        existing_tenant = await service.get_by_name(tenant_update.name)
        if existing_tenant and not existing_tenant.deleted_at:
            raise AlreadyExistsException(
                f"Tenant '{tenant_update.name}' already exists"
            )

    # Update the tenant
    updated_tenant = await service.update(tenant_id, tenant_update)
    return updated_tenant


@router.delete("/{tenant_id}", status_code=204, dependencies=[Depends(get_admin_user)])
async def delete_tenant(tenant_id: int, session: SessionDep):
    """Delete a tenant (soft delete)."""
    service = TenantService(session)
    tenant = await service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    await service.delete(tenant_id)


@router.post(
    "/{tenant_id}/expire",
    response_model=TenantPublic,
    dependencies=[Depends(get_admin_user)],
)
async def expire_tenant(tenant_id: int, session: SessionDep):
    """Mark a tenant as expired."""
    service = TenantService(session)
    tenant = await service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    # Update status to expired
    updated_tenant = await service.update_status(tenant_id, TenantStatusEnum.EXPIRED)
    return updated_tenant


@router.post(
    "/{tenant_id}/activate",
    response_model=TenantPublic,
    dependencies=[Depends(get_admin_user)],
)
async def activate_tenant(tenant_id: int, session: SessionDep):
    """Activate a tenant."""
    service = TenantService(session)
    tenant = await service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    # Update status to active
    updated_tenant = await service.update_status(tenant_id, TenantStatusEnum.ACTIVE)
    return updated_tenant


@router.post(
    "/{tenant_id}/suspend",
    response_model=TenantPublic,
    dependencies=[Depends(get_admin_user)],
)
async def suspend_tenant(tenant_id: int, session: SessionDep):
    """Suspend a tenant."""
    service = TenantService(session)
    tenant = await service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    # Update status to suspended
    updated_tenant = await service.update_status(tenant_id, TenantStatusEnum.SUSPENDED)
    return updated_tenant


@router.post(
    "/{tenant_id}/activate-resources",
    response_model=TenantWithResources,
    dependencies=[Depends(get_admin_user)],
)
async def activate_tenant_resources(
    tenant_id: int, activation: TenantResourceActivation, session: SessionDep
):
    """
    Activate tenant resources to start using.

    This endpoint activates GPU resources for a tenant, changing status from ACTIVE to INUSE.
    It sets the resource_start_time and prepares for usage tracking.

    Request Body:
        - gpu_ids: List of GPU IDs to activate. If empty, activate all allocated resources.
        - resource_start_time: Activation start time. If not provided, use current time.
        - operator: Who is performing this operation
        - reason: Reason for activation

    Note: After activation, the scheduled task will start generating usage_details.
    """
    # Verify tenant exists
    tenant_service = TenantService(session)
    tenant = await tenant_service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    # Check tenant status
    if tenant.status == TenantStatusEnum.INUSE:
        raise BadRequestException(
            f"Tenant '{tenant.name}' resources are already activated and in use"
        )

    resource_service = TenantResourceService(session)
    adjustment_service = TenantResourceAdjustmentService(session)

    # Get tenant's allocated resources
    all_resources = await resource_service.get_by_tenant_id(tenant_id)
    if not all_resources:
        raise BadRequestException(
            f"Tenant '{tenant.name}' has no allocated resources to activate"
        )

    # Determine which resources to activate
    if activation.gpu_ids:
        # Activate specific GPUs
        gpu_id_to_resource = {r.gpu_id: r for r in all_resources if r.gpu_id}
        resources_to_activate = []
        for gpu_id in activation.gpu_ids:
            if gpu_id not in gpu_id_to_resource:
                raise NotFoundException(f"GPU {gpu_id} is not allocated to this tenant")
            resources_to_activate.append(gpu_id_to_resource[gpu_id])
    else:
        # Activate all allocated resources
        resources_to_activate = all_resources

    # Determine activation start time
    activation_start_time = activation.resource_start_time or datetime.now()
    if activation_start_time.tzinfo is not None:
        activation_start_time = activation_start_time.replace(tzinfo=None)

    # Update resource start times
    activated_resources = []
    for resource in resources_to_activate:
        # Update resource_start_time
        resource.resource_start_time = activation_start_time
        await resource.save(session)
        activated_resources.append(
            {
                "resource_id": resource.id,
                "worker_id": resource.worker_id,
                "gpu_id": resource.gpu_id,
                "activation_time": activation_start_time.isoformat(),
            }
        )

    # Update tenant status to INUSE and set resource_start_time
    tenant.status = TenantStatusEnum.INUSE
    tenant.resource_start_time = activation_start_time
    await tenant.save(session)

    # Record the resource activation in adjustment history
    await adjustment_service.create(
        TenantResourceAdjustmentCreate(
            tenant_id=tenant_id,
            adjustment_type=ResourceAdjustmentTypeEnum.ADD,
            adjustment_time=datetime.now(),
            operator=activation.operator or "system",
            adjustment_details={
                "action": "resource_activation",
                "resource_count": len(activated_resources),
                "resources": activated_resources,
                "activation_time": activation_start_time.isoformat(),
            },
            reason=activation.reason or "Activate resources for tenant usage",
        )
    )

    # Commit the transaction first
    await session.commit()

    # Refresh tenant object after commit to reload attributes
    await session.refresh(tenant)

    # Return tenant with updated resources
    resources = await resource_service.get_by_tenant_id(tenant_id)
    worker_ids = set()
    gpu_count = 0

    for resource in resources:
        worker_ids.add(resource.worker_id)
        if resource.gpu_id:
            gpu_count += 1

    return TenantWithResources(
        id=tenant.id,
        name=tenant.name,
        status=tenant.status,
        contact_person=tenant.contact_person,
        contact_email=tenant.contact_email,
        resource_start_time=tenant.resource_start_time,
        resource_end_time=tenant.resource_end_time,
        resources=resources,
        total_workers=len(worker_ids),
        total_gpus=gpu_count,
    )


@router.post(
    "/{tenant_id}/expand-resources",
    response_model=TenantWithResources,
    dependencies=[Depends(get_admin_user)],
)
async def expand_tenant_resources(
    tenant_id: int, expansion: TenantResourceExpansion, session: SessionDep
):
    """
    Expand tenant resources by adding new GPU allocations.

    This endpoint adds new GPU resources to an existing tenant.
    All changes are recorded in the adjustment history.

    Request Body:
        - resources: List of GPU resources to add
        - operator: Who is performing this operation
        - reason: Reason for expansion
    """
    # Verify tenant exists
    tenant_service = TenantService(session)
    tenant = await tenant_service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    if not expansion.resources:
        raise BadRequestException("No resources provided for expansion")

    resource_service = TenantResourceService(session)
    adjustment_service = TenantResourceAdjustmentService(session)

    # Get existing allocations to check for duplicates
    existing_resources = await resource_service.get_by_tenant_id(tenant_id)
    existing_gpu_ids = {r.gpu_id for r in existing_resources if r.gpu_id}

    # Remove timezone info from resource_end_time if present
    resource_end_time = tenant.resource_end_time
    if resource_end_time and resource_end_time.tzinfo is not None:
        resource_end_time = resource_end_time.replace(tzinfo=None)

    added_resources = []
    for resource_item in expansion.resources:
        # Check if GPU is already allocated to this tenant
        if resource_item.gpu_id in existing_gpu_ids:
            raise BadRequestException(
                f"GPU {resource_item.gpu_id} is already allocated to this tenant"
            )

        # Verify worker exists
        worker = await Worker.one_by_id(session, resource_item.worker_id)
        if not worker or worker.deleted_at:
            raise NotFoundException(
                f"Worker with ID {resource_item.worker_id} not found"
            )

        # Create resource allocation
        # If tenant is already INUSE, set resource_start_time to current time
        # Otherwise, use placeholder time (will be set on activation)
        if tenant.status == TenantStatusEnum.INUSE:
            resource_start_time = datetime.now()
        else:
            resource_start_time = datetime(1970, 1, 1)  # Placeholder

        resource_create = TenantResourceCreate(
            tenant_id=tenant_id,
            worker_id=resource_item.worker_id,
            gpu_id=resource_item.gpu_id,
            resource_start_time=resource_start_time,
            resource_end_time=resource_end_time,
            resource_config=resource_item.resource_config,
        )
        allocated_resource = await resource_service.create(resource_create)
        added_resources.append(
            {
                "resource_id": allocated_resource.id,
                "worker_id": resource_item.worker_id,
                "gpu_id": resource_item.gpu_id,
            }
        )

    # Record the resource expansion in adjustment history
    await adjustment_service.create(
        TenantResourceAdjustmentCreate(
            tenant_id=tenant_id,
            adjustment_type=ResourceAdjustmentTypeEnum.ADD,
            adjustment_time=datetime.now(),
            operator=expansion.operator or "system",
            adjustment_details={
                "action": "resource_expansion",
                "resource_count": len(added_resources),
                "resources": added_resources,
            },
            reason=expansion.reason or "Resource expansion",
        )
    )

    # Commit the transaction first
    await session.commit()

    # Refresh tenant object after commit to reload attributes
    await session.refresh(tenant)

    # Return tenant with updated resources
    resources = await resource_service.get_by_tenant_id(tenant_id)
    worker_ids = set()
    gpu_count = 0

    for resource in resources:
        worker_ids.add(resource.worker_id)
        if resource.gpu_id:
            gpu_count += 1

    return TenantWithResources(
        id=tenant.id,
        name=tenant.name,
        status=tenant.status,
        contact_person=tenant.contact_person,
        contact_email=tenant.contact_email,
        resource_start_time=tenant.resource_start_time,
        resource_end_time=tenant.resource_end_time,
        resources=resources,
        total_workers=len(worker_ids),
        total_gpus=gpu_count,
    )


@router.post(
    "/{tenant_id}/reduce-resources",
    response_model=TenantWithResources,
    dependencies=[Depends(get_admin_user)],
)
async def reduce_tenant_resources(
    tenant_id: int, reduction: TenantResourceReduction, session: SessionDep
):
    """
    Reduce tenant resources by removing GPU allocations.

    This endpoint removes GPU resources from an existing tenant.
    All changes are recorded in the adjustment history.

    Request Body:
        - gpu_ids: List of GPU IDs to remove (format: worker_name:gpu_type:gpu_index)
        - operator: Who is performing this operation
        - reason: Reason for reduction
    """
    # Verify tenant exists
    tenant_service = TenantService(session)
    tenant = await tenant_service.get_by_id(tenant_id)

    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {tenant_id} not found")

    if not reduction.gpu_ids:
        raise BadRequestException("No GPU IDs provided for reduction")

    resource_service = TenantResourceService(session)
    adjustment_service = TenantResourceAdjustmentService(session)

    # Get existing allocations
    existing_resources = await resource_service.get_by_tenant_id(tenant_id)
    gpu_id_to_resource = {r.gpu_id: r for r in existing_resources if r.gpu_id}

    removed_resources = []
    for gpu_id in reduction.gpu_ids:
        # Check if GPU is allocated to this tenant
        if gpu_id not in gpu_id_to_resource:
            raise NotFoundException(f"GPU {gpu_id} is not allocated to this tenant")

        resource = gpu_id_to_resource[gpu_id]

        # Delete the resource allocation (soft delete)
        await resource_service.delete(resource.id)
        removed_resources.append(
            {
                "resource_id": resource.id,
                "worker_id": resource.worker_id,
                "gpu_id": gpu_id,
            }
        )

    # Record the resource reduction in adjustment history
    await adjustment_service.create(
        TenantResourceAdjustmentCreate(
            tenant_id=tenant_id,
            adjustment_type=ResourceAdjustmentTypeEnum.REMOVE,
            adjustment_time=datetime.now(),
            operator=reduction.operator or "system",
            adjustment_details={
                "action": "resource_reduction",
                "resource_count": len(removed_resources),
                "resources": removed_resources,
            },
            reason=reduction.reason or "Resource reduction",
        )
    )

    # Commit the transaction first
    await session.commit()

    # Refresh tenant object after commit to reload attributes
    await session.refresh(tenant)

    # Return tenant with updated resources
    resources = await resource_service.get_by_tenant_id(tenant_id)
    worker_ids = set()
    gpu_count = 0

    for resource in resources:
        worker_ids.add(resource.worker_id)
        if resource.gpu_id:
            gpu_count += 1

    return TenantWithResources(
        id=tenant.id,
        name=tenant.name,
        status=tenant.status,
        contact_person=tenant.contact_person,
        contact_email=tenant.contact_email,
        resource_start_time=tenant.resource_start_time,
        resource_end_time=tenant.resource_end_time,
        resources=resources,
        total_workers=len(worker_ids),
        total_gpus=gpu_count,
    )
