from typing import Optional, List
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from gpustack.server.deps import SessionDep, EngineDep
from gpustack.schemas.workers import (
    Worker,
    WorkerListParams,
    GPUDeviceInfo,
)
from gpustack.schemas.common import PaginatedList


router = APIRouter()


class GPUWithWorkerInfo(GPUDeviceInfo):
    """GPU device with worker information."""

    # GPU device ID (format: worker_name:gpu_type:gpu_index)
    id: str
    # Worker information
    worker_id: int
    worker_name: str
    worker_ip: str
    worker_ifname: str
    worker_state: Optional[str] = None
    cluster_id: int


class WorkerWithGPUsPublic(BaseModel):
    """Worker with all GPU devices information."""

    # Worker basic info
    id: int
    name: str
    ip: str
    ifname: str
    state: Optional[str] = None
    cluster_id: int
    rack_id: Optional[int] = None
    # GPU devices list
    gpu_devices: List[GPUWithWorkerInfo] = Field(default_factory=list)
    total_gpus: int = Field(default=0)


WorkersWithGPUsPublic = PaginatedList[WorkerWithGPUsPublic]


@router.get("", response_model=WorkersWithGPUsPublic)
async def get_workers_with_gpus(
    engine: EngineDep,
    session: SessionDep,
    params: WorkerListParams = Depends(),
    search: str = None,
    cluster_id: int = None,
    rack_id: int = None,
    state: str = None,
):
    """
    Get workers with their GPU devices information.

    This endpoint combines worker information with GPU device details from the
    gpu_devices_view. It supports filtering by cluster, rack, state, and search.

    Query Parameters:
        - search: Fuzzy search by worker name
        - cluster_id: Filter by cluster ID
        - rack_id: Filter by rack ID
        - state: Filter by worker state
        - watch: Enable streaming mode for real-time updates
        - page: Page number for pagination
        - perPage: Number of items per page
        - orderBy: Sort field and direction (e.g., "name:asc")
    """
    # Build query filters
    fields = {"deleted_at": None}
    fuzzy_fields = {}

    if search:
        fuzzy_fields["name"] = search
    if cluster_id:
        fields["cluster_id"] = cluster_id
    if rack_id:
        fields["rack_id"] = rack_id
    if state:
        fields["state"] = state

    # Handle streaming mode (watch=true)
    if params.watch:

        async def worker_stream_with_gpus():
            async for event_data in Worker.streaming(
                engine, fields=fields, fuzzy_fields=fuzzy_fields
            ):
                yield event_data

        return StreamingResponse(
            worker_stream_with_gpus(),
            media_type="text/event-stream",
        )

    # Get paginated workers
    worker_list = await Worker.paginated_by_query(
        session=session,
        fields=fields,
        fuzzy_fields=fuzzy_fields,
        page=params.page,
        per_page=params.perPage,
        order_by=params.order_by,
    )

    # Build response with GPU devices
    result_items = []
    for worker in worker_list.items:
        gpu_devices_list = []
        total_gpus = 0

        # Extract GPU devices from worker status
        if (
            worker.status
            and hasattr(worker.status, 'gpu_devices')
            and worker.status.gpu_devices
        ):
            for gpu in worker.status.gpu_devices:
                # Generate GPU ID (format: worker_name:gpu_type:gpu_index)
                gpu_type = gpu.type if gpu.type else "unknown"
                gpu_id = f"{worker.name}:{gpu_type}:{gpu.index}"

                # Create GPU device with worker info
                gpu_with_worker = GPUWithWorkerInfo(
                    id=gpu_id,
                    worker_id=worker.id,
                    worker_name=worker.name,
                    worker_ip=worker.ip,
                    worker_ifname=worker.ifname,
                    worker_state=worker.state.value if worker.state else None,
                    cluster_id=worker.cluster_id,
                    # GPU device fields
                    vendor=gpu.vendor,
                    type=gpu.type,
                    index=gpu.index,
                    device_index=gpu.device_index,
                    device_chip_index=gpu.device_chip_index,
                    arch_family=gpu.arch_family,
                    name=gpu.name,
                    uuid=gpu.uuid,
                    driver_version=gpu.driver_version,
                    runtime_version=gpu.runtime_version,
                    compute_capability=gpu.compute_capability,
                    core=gpu.core.model_dump() if gpu.core else None,
                    memory=gpu.memory.model_dump() if gpu.memory else None,
                    temperature=gpu.temperature,
                    network=gpu.network.model_dump() if gpu.network else None,
                    log=gpu.log,
                )
                gpu_devices_list.append(gpu_with_worker)
            total_gpus = len(gpu_devices_list)

        # Create worker with GPUs response
        worker_with_gpus = WorkerWithGPUsPublic(
            id=worker.id,
            name=worker.name,
            ip=worker.ip,
            ifname=worker.ifname,
            state=worker.state.value if worker.state else None,
            cluster_id=worker.cluster_id,
            rack_id=worker.rack_id,
            gpu_devices=gpu_devices_list,
            total_gpus=total_gpus,
        )
        result_items.append(worker_with_gpus)

    return WorkersWithGPUsPublic(
        items=result_items,
        pagination=worker_list.pagination,
    )


@router.get("/{worker_id}", response_model=WorkerWithGPUsPublic)
async def get_worker_with_gpus(worker_id: int, session: SessionDep):
    """
    Get a single worker with its GPU devices information.

    Path Parameters:
        - worker_id: Worker ID
    """
    from gpustack.api.exceptions import NotFoundException

    worker = await Worker.one_by_id(session, worker_id)
    if not worker or worker.deleted_at:
        raise NotFoundException(message=f"Worker with ID {worker_id} not found")

    gpu_devices_list = []
    total_gpus = 0

    # Extract GPU devices from worker status
    if (
        worker.status
        and hasattr(worker.status, 'gpu_devices')
        and worker.status.gpu_devices
    ):
        for gpu in worker.status.gpu_devices:
            # Generate GPU ID
            gpu_type = gpu.type if gpu.type else "unknown"
            gpu_id = f"{worker.name}:{gpu_type}:{gpu.index}"

            # Create GPU device with worker info
            gpu_with_worker = GPUWithWorkerInfo(
                id=gpu_id,
                worker_id=worker.id,
                worker_name=worker.name,
                worker_ip=worker.ip,
                worker_ifname=worker.ifname,
                worker_state=worker.state.value if worker.state else None,
                cluster_id=worker.cluster_id,
                # GPU device fields
                vendor=gpu.vendor,
                type=gpu.type,
                index=gpu.index,
                device_index=gpu.device_index,
                device_chip_index=gpu.device_chip_index,
                arch_family=gpu.arch_family,
                name=gpu.name,
                uuid=gpu.uuid,
                driver_version=gpu.driver_version,
                runtime_version=gpu.runtime_version,
                compute_capability=gpu.compute_capability,
                core=gpu.core.model_dump() if gpu.core else None,
                memory=gpu.memory.model_dump() if gpu.memory else None,
                temperature=gpu.temperature,
                network=gpu.network.model_dump() if gpu.network else None,
                log=gpu.log,
            )
            gpu_devices_list.append(gpu_with_worker)
        total_gpus = len(gpu_devices_list)

    return WorkerWithGPUsPublic(
        id=worker.id,
        name=worker.name,
        ip=worker.ip,
        ifname=worker.ifname,
        state=worker.state.value if worker.state else None,
        cluster_id=worker.cluster_id,
        rack_id=worker.rack_id,
        gpu_devices=gpu_devices_list,
        total_gpus=total_gpus,
    )
