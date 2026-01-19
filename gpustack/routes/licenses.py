from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, Field

from gpustack.server.db import get_session
from gpustack.schemas.licenses import (
    License,
    LicenseCreate,
    LicenseUpdate,
    LicensePublic,
    LicensesPublic,
    LicenseListParams,
    LicenseActivation,
    LicenseActivationCreate,
    LicenseActivationPublic,
    LicenseStatusEnum,
)
from gpustack.schemas.workers import Worker


router = APIRouter(prefix="/licenses", tags=["licenses"])


# New Pydantic models for license activation status API
class GPULicenseStatus(BaseModel):
    """GPU license activation status."""

    gpu_id: str = Field(..., description="GPU ID")
    gpu_type: Optional[str] = Field(None, description="GPU型号")
    gpu_sn: str = Field(..., description="GPU序列号(uuid)")
    license_expiration_time: Optional[datetime] = Field(
        None, description="License到期时间"
    )
    status: str = Field(..., description="状态(已激活, 快到期, 未激活, 已过期)")


class NodeLicenseStatus(BaseModel):
    """Node license activation status."""

    worker_name: str = Field(..., description="节点名称")
    ip: str = Field(..., description="IP地址")
    cpu: Optional[int] = Field(None, description="CPU核心数")
    memory: Optional[int] = Field(None, description="内存大小(MB)")
    status: str = Field(..., description="状态(已激活, 快到期, 未激活, 已过期)")
    gpus: List[GPULicenseStatus] = Field(default_factory=list, description="GPU列表")


@router.post("/", response_model=LicensePublic)
async def create_license(
    license_data: LicenseCreate, session: AsyncSession = Depends(get_session)
):
    """
    Create a new license.
    """
    # Check if license code already exists
    existing_license = await session.exec(
        select(License).where(License.license_code == license_data.license_code)
    )
    if existing_license.first():
        raise HTTPException(
            status_code=400,
            detail=f"License with code '{license_data.license_code}' already exists",
        )

    # Check if license id already exists
    existing_license = await session.exec(
        select(License).where(License.license_id == license_data.license_id)
    )
    if existing_license.first():
        raise HTTPException(
            status_code=400,
            detail=f"License with id '{license_data.license_id}' already exists",
        )

    db_license = License.model_validate(license_data)
    session.add(db_license)
    await session.commit()
    await session.refresh(db_license)
    return db_license


@router.get("/", response_model=LicensesPublic)
async def list_licenses(
    params: LicenseListParams = Depends(LicenseListParams),
    session: AsyncSession = Depends(get_session),
):
    """
    List all licenses with pagination and filtering.
    """
    # Build order by list from params
    order_by = []
    if params.sort_by and params.order:
        order_by = [(params.sort_by, params.order)]

    # Get paginated items using the model's paginated_by_query method
    paginated_result = await License.paginated_by_query(
        session=session, page=params.page, per_page=params.per_page, order_by=order_by
    )

    # Convert to response model
    return LicensesPublic(
        items=[LicensePublic.model_validate(item) for item in paginated_result.items],
        pagination=paginated_result.pagination,
    )


def _group_activations_by_worker_and_gpu(activations: List[LicenseActivation]) -> dict:
    """
    Group license activations by worker_id and gpu_sn.
    """
    activation_map = {}
    for activation in activations:
        if activation.worker_id not in activation_map:
            activation_map[activation.worker_id] = {}
        activation_map[activation.worker_id][activation.gpu_sn] = activation
    return activation_map


def _create_node_status(worker: Worker) -> NodeLicenseStatus:
    """
    Create NodeLicenseStatus object for a worker.
    """
    cpu_total = None
    if worker.status and worker.status.cpu:
        cpu_total = worker.status.cpu.total
    memory_total = None
    if worker.status and worker.status.memory:
        memory_total = worker.status.memory.total
    return NodeLicenseStatus(
        worker_name=worker.name,
        ip=worker.ip,
        cpu=cpu_total,
        memory=memory_total,
        status="未激活",
        gpus=[],
    )


def _process_gpu_device(
    gpu,
    worker_name: str,
    worker_activations: dict,
    now: datetime,
    soon_expire_threshold: timedelta,
) -> GPULicenseStatus:
    """
    Process a single GPU device and return its license status.
    """
    # Generate gpu_id
    if gpu.type and gpu.index is not None:
        gpu_id = f"{worker_name}:{gpu.type}:{gpu.index}"
    else:
        gpu_id = f"{worker_name}:unknown:{gpu.index}"
    gpu_sn = gpu.uuid if gpu.uuid else "unknown"

    # Check if this GPU has an activation
    activation = worker_activations.get(gpu_sn)
    gpu_status = "未激活"
    expiration_time = None

    if activation:
        expiration_time = activation.expiration_time

        if expiration_time and now > expiration_time:
            gpu_status = "已过期"
        elif expiration_time and (expiration_time - now) < soon_expire_threshold:
            gpu_status = "快到期"
        else:
            gpu_status = "已激活"

    # Create GPU status
    return GPULicenseStatus(
        gpu_id=gpu_id,
        gpu_type=gpu.arch_family if gpu.arch_family else None,
        gpu_sn=gpu_sn,
        license_expiration_time=expiration_time,
        status=gpu_status,
    )


def _determine_node_status(node_status: NodeLicenseStatus) -> NodeLicenseStatus:
    """
    Determine node status based on GPU statuses.
    """
    if node_status.gpus:
        # Check if all GPUs are in the same status
        all_statuses = {gpu.status for gpu in node_status.gpus}

        if "已过期" in all_statuses:
            node_status.status = "已过期"
        elif "快到期" in all_statuses:
            node_status.status = "快到期"
        elif "未激活" in all_statuses:
            node_status.status = "未激活"
        else:
            node_status.status = "已激活"
    return node_status


@router.get("/activation-status", response_model=List[NodeLicenseStatus])
async def get_license_activation_status(session: AsyncSession = Depends(get_session)):
    """
    Get license activation status list by node and GPU.
    Returns nodes with their GPUs and their license activation status.
    """
    # Get all workers
    workers = await session.exec(select(Worker))
    workers = workers.all()

    # Get all license activations
    activations = await session.exec(select(LicenseActivation))
    activations = activations.all()

    # Group activations by worker_id and gpu_sn
    activation_map = _group_activations_by_worker_and_gpu(activations)

    # Prepare response data
    node_status_list = []
    now = datetime.utcnow()
    soon_expire_threshold = timedelta(days=7)

    for worker in workers:
        # Create node status
        node_status = _create_node_status(worker)

        # Get activations for this worker
        worker_activations = activation_map.get(worker.id, {})

        # Process each GPU device
        if worker.status and worker.status.gpu_devices:
            gpu_devices = worker.status.gpu_devices
        else:
            gpu_devices = []

        for gpu in gpu_devices:
            gpu_status = _process_gpu_device(
                gpu, worker.name, worker_activations, now, soon_expire_threshold
            )
            node_status.gpus.append(gpu_status)

        # Determine node status based on GPU statuses
        node_status = _determine_node_status(node_status)

        node_status_list.append(node_status)

    return node_status_list


@router.get("/{license_id}", response_model=LicensePublic)
async def get_license(license_id: int, session: AsyncSession = Depends(get_session)):
    """
    Get a license by ID.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")
    return license


@router.put("/{license_id}", response_model=LicensePublic)
async def update_license(
    license_id: int,
    license_update: LicenseUpdate,
    session: AsyncSession = Depends(get_session),
):
    """
    Update a license.
    """
    db_license = await session.get(License, license_id)
    if not db_license:
        raise HTTPException(status_code=404, detail="License not found")

    update_data = license_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_license, field, value)

    session.add(db_license)
    await session.commit()
    await session.refresh(db_license)
    return db_license


@router.delete("/{license_id}")
async def delete_license(license_id: int, session: AsyncSession = Depends(get_session)):
    """
    Delete a license.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    await session.delete(license)
    await session.commit()
    return {"message": "License deleted successfully"}


@router.post("/{license_id}/activate")
async def activate_license(
    license_id: int, session: AsyncSession = Depends(get_session)
):
    """
    Activate a license.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    if license.status == LicenseStatusEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="License is already activated")

    license.status = LicenseStatusEnum.ACTIVE
    license.activation_time = datetime.utcnow()
    session.add(license)
    await session.commit()
    await session.refresh(license)
    return {"message": "License activated successfully", "license": license}


@router.post("/{license_id}/revoke")
async def revoke_license(license_id: int, session: AsyncSession = Depends(get_session)):
    """
    Revoke a license.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    if license.status == LicenseStatusEnum.REVOKED:
        raise HTTPException(status_code=400, detail="License is already revoked")

    license.status = LicenseStatusEnum.REVOKED
    session.add(license)
    await session.commit()
    await session.refresh(license)

    # Update all activations for this license to revoked
    activations = await session.exec(
        select(LicenseActivation).where(LicenseActivation.license_id == license_id)
    )
    for activation in activations:
        activation.status = LicenseStatusEnum.REVOKED
        session.add(activation)
    await session.commit()

    return {"message": "License revoked successfully", "license": license}


# License Activation Routes


@router.post("/activations", response_model=LicenseActivationPublic)
async def create_license_activation(
    activation_data: LicenseActivationCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    Create a new license activation.
    """
    # Find the license by license code
    license = await session.exec(
        select(License).where(License.license_code == activation_data.license_code)
    )
    license = license.first()

    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    if license.status != LicenseStatusEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="License is not active")

    # Check if GPU SN is already activated
    existing_activation = await session.exec(
        select(LicenseActivation).where(
            LicenseActivation.gpu_sn == activation_data.gpu_sn
        )
    )
    if existing_activation.first():
        raise HTTPException(
            status_code=400,
            detail=f"GPU with SN '{activation_data.gpu_sn}' is already activated",
        )

    # Check if max GPUs limit is reached
    activation_count = await session.exec(
        select(func.count(LicenseActivation.id)).where(
            LicenseActivation.license_id == license.id
        )
    )
    if activation_count.first() >= license.max_gpus and license.max_gpus > 0:
        raise HTTPException(
            status_code=400,
            detail=f"License GPU limit reached. Maximum {license.max_gpus} GPUs allowed",
        )

    # Create activation
    activation = LicenseActivation.model_validate(activation_data)
    activation.license_id = license.id
    activation.expiration_time = license.expiration_time
    session.add(activation)
    await session.commit()
    await session.refresh(activation)
    return activation


@router.get("/activations", response_model=List[LicenseActivationPublic])
async def list_license_activations(
    license_id: Optional[int] = None,
    worker_id: Optional[int] = None,
    gpu_sn: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    List license activations with filtering.
    """
    query = select(LicenseActivation)

    if license_id:
        query = query.where(LicenseActivation.license_id == license_id)
    if worker_id:
        query = query.where(LicenseActivation.worker_id == worker_id)
    if gpu_sn:
        query = query.where(LicenseActivation.gpu_sn == gpu_sn)

    result = await session.exec(query)
    return result.all()


@router.get("/activations/{activation_id}", response_model=LicenseActivationPublic)
async def get_license_activation(
    activation_id: int, session: AsyncSession = Depends(get_session)
):
    """
    Get a license activation by ID.
    """
    activation = await session.get(LicenseActivation, activation_id)
    if not activation:
        raise HTTPException(status_code=404, detail="License activation not found")
    return activation


@router.delete("/activations/{activation_id}")
async def delete_license_activation(
    activation_id: int, session: AsyncSession = Depends(get_session)
):
    """
    Delete a license activation.
    """
    activation = await session.get(LicenseActivation, activation_id)
    if not activation:
        raise HTTPException(status_code=404, detail="License activation not found")

    await session.delete(activation)
    await session.commit()
    return {"message": "License activation deleted successfully"}
