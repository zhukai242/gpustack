from datetime import datetime, timedelta, timezone
import secrets
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, Field

from gpustack.server.db import get_session
from gpustack.server.deps import CurrentUserDep
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
    LicenseTypeEnum,
    LicenseOperation,
    LicenseOperationPublic,
    LicenseOperationTypeEnum,
    BatchLicenseActivationRequest,
    BatchLicenseRenewalRequest,
)
from gpustack.schemas.workers import Worker
from gpustack.schemas.gpu_devices import GPUDevice


router = APIRouter(prefix="/licenses", tags=["licenses"])


async def _record_license_operation(
    session: AsyncSession,
    license_id: int,
    operation_type: LicenseOperationTypeEnum,
    operator: str = "system",
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    description: Optional[str] = None,
):
    """
    Record a license operation in the license_operations table.
    This function should be called within the main transaction, before session.commit().
    """
    from sqlalchemy import text

    # 使用直接SQL语句，避免触发事件监听器
    # 确保在同一个事务中执行，避免greenlet_spawn错误
    insert_operation_stmt = text(
        """
    INSERT INTO license_operations
    (license_id, operation_type, operator, old_value, new_value, description,
     created_at, updated_at)
    VALUES (:license_id, :operation_type, :operator, :old_value, :new_value,
            :description, NOW(), NOW())
    RETURNING id
    """
    )

    result = await session.execute(
        insert_operation_stmt,
        {
            "license_id": license_id,
            "operation_type": operation_type.value,
            "operator": operator,
            "old_value": old_value,
            "new_value": new_value,
            "description": description,
        },
    )

    return result.scalar()


# New Pydantic models for license activation status API
class GPULicenseStatus(BaseModel):
    """GPU license activation status."""

    gpu_id: str = Field(..., description="GPU ID")
    gpu_type: Optional[str] = Field(None, description="GPU型号")
    gpu_sn: str = Field(..., description="GPU序列号(uuid)")
    license_id: Optional[int] = Field(None, description="License ID")
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
    node_state: str = Field(..., description="节点状态(来自workers表的state字段)")
    gpus: List[GPULicenseStatus] = Field(default_factory=list, description="GPU列表")


class LicenseActivationRequest(BaseModel):
    """License activation request model."""

    activation_code: str = Field(..., description="激活码")
    gpu_id: str = Field(..., description="GPU ID")
    gpu_sn: str = Field(..., description="GPU序列号(uuid)")
    gpu_model: Optional[str] = Field(None, description="GPU型号")
    worker_id: Optional[int] = Field(None, description="节点ID")


class GPULicenseStats(BaseModel):
    """GPU license statistics."""

    all_gpus: int = Field(..., description="所有GPU个数")
    activated_gpus: int = Field(..., description="已激活GPU个数")
    inactive_gpus: int = Field(..., description="未激活GPU个数")
    soon_expire_gpus: int = Field(..., description="快到期GPU个数(30天)")
    expired_gpus: int = Field(..., description="已过期GPU个数")
    soon_expire_list: List[NodeLicenseStatus] = Field(
        default_factory=list, description="快到期GPU列表"
    )


@router.post("/", response_model=LicensePublic)
async def create_license(
    license_data: LicenseCreate,
    user: CurrentUserDep,
    session: AsyncSession = Depends(get_session),
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

    # Record license creation operation within the main transaction
    await _record_license_operation(
        session=session,
        license_id=db_license.id,
        operation_type=LicenseOperationTypeEnum.CREATE,
        operator=user.username,
        new_value=str(db_license.model_dump()),
        description=f"Create license {db_license.license_id}",
    )

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
        node_state=worker.state,
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
    license_id = None

    if activation:
        expiration_time = activation.expiration_time
        license_id = activation.license_id

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
        license_id=license_id,
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
async def get_license_activation_status(
    node_name: Optional[str] = None,
    status: Optional[str] = None,
    activation_time_start: Optional[datetime] = None,
    activation_time_end: Optional[datetime] = None,
    expiration_time_start: Optional[datetime] = None,
    expiration_time_end: Optional[datetime] = None,
    sort_by_expiration: Optional[str] = None,  # asc or desc
    session: AsyncSession = Depends(get_session),
):
    """
    Get license activation status list by node and GPU.
    Returns nodes with their GPUs and their license activation status.

    Args:
        node_name: 节点名称（模糊匹配）
        status: 激活状态（已激活, 快到期, 未激活, 已过期）
        activation_time_start: 激活时间起始
        activation_time_end: 激活时间结束
        expiration_time_start: 到期时间起始
        expiration_time_end: 到期时间结束
        sort_by_expiration: 按照到期时间排序（asc/desc）
    """
    # Get all workers with optional filtering by node name
    query = select(Worker)
    if node_name:
        query = query.where(Worker.name.like(f"%{node_name}%"))

    workers = await session.exec(query)
    workers = workers.all()

    # Get all license activations with optional filtering
    activation_query = select(LicenseActivation)

    # Filter by activation time range
    if activation_time_start:
        activation_query = activation_query.where(
            LicenseActivation.activation_time >= activation_time_start
        )
    if activation_time_end:
        activation_query = activation_query.where(
            LicenseActivation.activation_time <= activation_time_end
        )

    # Filter by expiration time range
    if expiration_time_start:
        activation_query = activation_query.where(
            LicenseActivation.expiration_time >= expiration_time_start
        )
    if expiration_time_end:
        activation_query = activation_query.where(
            LicenseActivation.expiration_time <= expiration_time_end
        )

    activations = await session.exec(activation_query)
    activations = activations.all()

    # Group activations by worker_id and gpu_sn
    activation_map = _group_activations_by_worker_and_gpu(activations)

    # Prepare response data
    node_status_list = []
    now = datetime.now(timezone.utc)
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

        # Filter by status if provided
        if status and node_status.status != status:
            continue

        node_status_list.append(node_status)

    # Sort by expiration time if requested
    if sort_by_expiration:

        def get_earliest_expiration(node):
            """Get the earliest expiration time for a node."""
            if not node.gpus:
                return datetime.max
            # Get the earliest expiration time among all GPUs
            expiration_times = [
                gpu.license_expiration_time
                for gpu in node.gpus
                if gpu.license_expiration_time
            ]
            if not expiration_times:
                return datetime.max
            return min(expiration_times)

        # Sort the node list by earliest GPU expiration time
        node_status_list.sort(
            key=get_earliest_expiration, reverse=(sort_by_expiration.lower() == "desc")
        )

    return node_status_list


@router.get("/gpu-license-stats", response_model=GPULicenseStats)
async def get_gpu_license_stats(session: AsyncSession = Depends(get_session)):
    """
    Get GPU license statistics, including:
    - All GPU count
    - Activated GPU count
    - Inactive GPU count
    - Soon expire GPU count (30 days)
    - Expired GPU count
    - Soon expire GPU list with detailed information
    """
    # Get all license activation status
    all_node_status = await get_license_activation_status(session=session)

    # Calculate statistics
    all_gpus = 0
    activated_gpus = 0
    inactive_gpus = 0
    soon_expire_gpus = 0
    expired_gpus = 0
    soon_expire_nodes = []

    for node in all_node_status:
        has_soon_expire = False

        for gpu in node.gpus:
            all_gpus += 1

            if gpu.status == "已激活":
                activated_gpus += 1
            elif gpu.status == "未激活":
                inactive_gpus += 1
            elif gpu.status == "已过期":
                expired_gpus += 1

            # Check if this GPU is soon expire
            if gpu.status == "快到期":
                soon_expire_gpus += 1
                has_soon_expire = True

        # Add to soon expire list if any GPU on this node is soon expire
        if has_soon_expire:
            soon_expire_nodes.append(node)

    # Return the statistics
    return GPULicenseStats(
        all_gpus=all_gpus,
        activated_gpus=activated_gpus,
        inactive_gpus=inactive_gpus,
        soon_expire_gpus=soon_expire_gpus,
        expired_gpus=expired_gpus,
        soon_expire_list=soon_expire_nodes,
    )


# License Operation Routes - Move before generic {license_id} route
@router.get("/operations", response_model=List[LicenseOperationPublic])
async def list_license_operations(
    license_id: Optional[int] = None,
    operation_type: Optional[LicenseOperationTypeEnum] = None,
    operator: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    List license operations with filtering.
    """
    query = select(LicenseOperation)

    if license_id:
        query = query.where(LicenseOperation.license_id == license_id)
    if operation_type:
        query = query.where(LicenseOperation.operation_type == operation_type)
    if operator:
        query = query.where(LicenseOperation.operator == operator)
    if start_time:
        query = query.where(LicenseOperation.operation_time >= start_time)
    if end_time:
        query = query.where(LicenseOperation.operation_time <= end_time)

    # Order by operation time descending
    query = query.order_by(LicenseOperation.operation_time.desc())

    result = await session.exec(query)
    return result.all()


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
    user: CurrentUserDep,
    session: AsyncSession = Depends(get_session),
):
    """
    Update a license.
    """
    db_license = await session.get(License, license_id)
    if not db_license:
        raise HTTPException(status_code=404, detail="License not found")

    # Save old value for operation record
    old_value = str(db_license.model_dump())

    update_data = license_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_license, field, value)

    session.add(db_license)
    await session.commit()
    await session.refresh(db_license)

    # Record license update operation within the main transaction
    await _record_license_operation(
        session=session,
        license_id=db_license.id,
        operation_type=LicenseOperationTypeEnum.UPDATE,
        operator=user.username,
        old_value=old_value,
        new_value=str(db_license.model_dump()),
        description=f"Update license {db_license.license_id}",
    )

    return db_license


@router.delete("/{license_id}")
async def delete_license(
    license_id: int, user: CurrentUserDep, session: AsyncSession = Depends(get_session)
):
    """
    Delete a license.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    # Save license data for operation record before deletion
    license_data = str(license.model_dump())
    license_id_str = license.license_id

    await session.delete(license)
    await session.commit()

    # Record license delete operation within the main transaction
    await _record_license_operation(
        session=session,
        license_id=license_id,
        operation_type=LicenseOperationTypeEnum.DELETE,
        operator=user.username,
        old_value=license_data,
        description=f"Delete license {license_id_str}",
    )

    return {"message": "License deleted successfully"}


@router.post("/activate")
async def activate_license(
    request: LicenseActivationRequest,
    user: CurrentUserDep,
    session: AsyncSession = Depends(get_session),
):
    """
    Activate a license using activation code and GPU ID.
    """
    # 1. Check if this GPU is already activated with the same license
    existing_activation = await session.exec(
        select(LicenseActivation).where(
            LicenseActivation.license_code == request.activation_code,
            LicenseActivation.gpu_sn == request.gpu_sn,
        )
    )
    if existing_activation.first():
        raise HTTPException(
            status_code=400,
            detail=f"GPU with SN '{request.gpu_sn}' is already activated with "
            f"this license code",
        )

    # 2. Call external API to get license information (reserved for future implementation)
    async def get_license_info_from_external_api(activation_code: str):
        """
        Simulate calling external API to get license information.
        """
        # Generate a random string to ensure uniqueness
        random_str = secrets.token_hex(4)
        return {
            "license_id": f"license-{random_str}-{activation_code[:8]}",
            "license_code": activation_code,
            "license_type": LicenseTypeEnum.ENTERPRISE,
            "max_gpus": 1,
            "expiration_time": datetime.now(timezone.utc) + timedelta(days=365),
            "issuer": "external-api",
            "description": "License from external API",
        }

    license_info = await get_license_info_from_external_api(request.activation_code)

    # 3. Get or create license
    existing_license = await session.exec(
        select(License).where(License.license_code == license_info["license_code"])
    )
    existing_license = existing_license.first()

    if existing_license:
        # License exists, update if not active
        license = existing_license
        if license.status != LicenseStatusEnum.ACTIVE:
            license.status = LicenseStatusEnum.ACTIVE
            license.activation_time = datetime.now(timezone.utc)
            license.updated_at = datetime.now(timezone.utc)
            session.add(license)
            await session.flush()
    else:
        # Create new license
        license = License(
            license_id=license_info["license_id"],
            license_code=license_info["license_code"],
            license_type=license_info["license_type"],
            status=LicenseStatusEnum.ACTIVE,
            activation_time=datetime.now(timezone.utc),
            expiration_time=license_info["expiration_time"],
            issued_time=datetime.now(timezone.utc),
            issuer=license_info["issuer"],
            max_gpus=license_info["max_gpus"],
            description=license_info["description"],
        )
        session.add(license)
        await session.flush()

    # 4. Check if license has reached max GPUs limit
    activation_count = await session.exec(
        select(func.count(LicenseActivation.id)).where(
            LicenseActivation.license_id == license.id
        )
    )
    activation_count = activation_count.one()

    if activation_count >= license.max_gpus and license.max_gpus > 0:
        raise HTTPException(
            status_code=400,
            detail=f"License GPU limit reached. Maximum {license.max_gpus} GPUs allowed",
        )

    # 5. Create license activation record
    activation = LicenseActivation(
        license_external_id=license_info["license_id"],
        license_code=license_info["license_code"],
        license_id=license.id,
        worker_id=request.worker_id,
        gpu_id=request.gpu_id,
        gpu_sn=request.gpu_sn,
        gpu_model=request.gpu_model,
        status=LicenseStatusEnum.ACTIVE,
        activation_time=datetime.now(timezone.utc),
        expiration_time=license_info["expiration_time"],
        activated_by="system",
    )
    session.add(activation)
    await session.flush()

    # 6. Record license operation
    license_operation = LicenseOperation(
        license_id=license.id,
        operation_type=LicenseOperationTypeEnum.ACTIVATE,
        operator=user.username,
        operation_time=datetime.now(timezone.utc),
        description=f"Activate GPU {request.gpu_sn} with license {license_info['license_id']}",
    )
    session.add(license_operation)

    # 7. Commit all changes at once
    await session.commit()
    await session.refresh(license)
    await session.refresh(activation)

    # 8. Return result
    return {
        "message": "License activated successfully",
        "license": license,
        "activation": activation,
    }


@router.post("/{license_id}/revoke")
async def revoke_license(
    license_id: int, user: CurrentUserDep, session: AsyncSession = Depends(get_session)
):
    """
    Revoke a license.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    if license.status == LicenseStatusEnum.REVOKED:
        raise HTTPException(status_code=400, detail="License is already revoked")

    # Save old value for operation record
    old_value = str(license.model_dump())

    license.status = LicenseStatusEnum.REVOKED
    session.add(license)
    await session.commit()
    await session.refresh(license)

    # Record license revocation operation within the main transaction
    await _record_license_operation(
        session=session,
        license_id=license.id,
        operation_type=LicenseOperationTypeEnum.REVOKE,
        operator=user.username,
        old_value=old_value,
        new_value=str(license.model_dump()),
        description=f"Revoke license {license.license_id}",
    )

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


@router.post("/renew")
async def renew_license(
    request: LicenseActivationRequest,
    user: CurrentUserDep,
    session: AsyncSession = Depends(get_session),
):
    """
    Renew a license for a specific GPU.
    """
    # 1. Check if this GPU is already activated
    existing_activation = await session.exec(
        select(LicenseActivation).where(
            LicenseActivation.gpu_sn == request.gpu_sn,
            LicenseActivation.status == LicenseStatusEnum.ACTIVE,
        )
    )
    existing_activation = existing_activation.first()
    if not existing_activation:
        raise HTTPException(
            status_code=400, detail=f"GPU with SN '{request.gpu_sn}' is not activated"
        )

    # 2. Call external API to get license information
    async def get_license_info_from_external_api(activation_code: str):
        """
        Simulate calling external API to get license information.
        """
        # Generate a random string to ensure uniqueness
        random_str = secrets.token_hex(4)
        return {
            "license_id": f"license-{random_str}-{activation_code[:8]}",
            "license_code": activation_code,
            "license_type": LicenseTypeEnum.ENTERPRISE,
            "max_gpus": 1,
            "expiration_time": datetime.now(timezone.utc) + timedelta(days=365),
            "issuer": "external-api",
            "description": "License from external API",
        }

    license_info = await get_license_info_from_external_api(request.activation_code)

    # 3. Get the license
    license = await session.get(License, existing_activation.license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    # 4. Update license expiration time
    license.expiration_time = license_info["expiration_time"]
    session.add(license)
    await session.flush()

    # 5. Update activation record expiration time
    existing_activation.expiration_time = license_info["expiration_time"]
    session.add(existing_activation)
    await session.flush()

    # 6. Record license operation
    license_operation = LicenseOperation(
        license_id=license.id,
        operation_type=LicenseOperationTypeEnum.RENEW,
        operator=user.username,
        operation_time=datetime.now(timezone.utc),
        description=f"Renew GPU {request.gpu_sn} license",
    )
    session.add(license_operation)

    # 7. Commit all changes at once
    await session.commit()
    await session.refresh(license)
    await session.refresh(existing_activation)

    # 8. Return result
    return {
        "message": "License renewed successfully",
        "license": license,
        "activation": existing_activation,
    }


@router.post("/activate-batch")
async def activate_license_batch(
    request: BatchLicenseActivationRequest,
    user: CurrentUserDep,
    session: AsyncSession = Depends(get_session),
):
    """
    Batch activate licenses for all GPUs on a worker.
    """
    # 1. Get all GPUs on the specified worker from gpu_devices_view
    gpus = await session.exec(
        select(GPUDevice).where(GPUDevice.worker_id == request.worker_id)
    )
    gpus = gpus.all()
    if not gpus:
        raise HTTPException(
            status_code=404, detail=f"No GPUs found on worker {request.worker_id}"
        )

    # 2. Check if we have enough activation codes
    if len(request.activation_code) < len(gpus):
        raise HTTPException(status_code=400, detail="Not enough activation codes")

    # 3. Call external API to get license information
    async def get_license_info_from_external_api(activation_code: str):
        """
        Simulate calling external API to get license information.
        """
        # Generate a random string to ensure uniqueness
        random_str = secrets.token_hex(4)
        return {
            "license_id": f"license-{random_str}-{activation_code[:8]}",
            "license_code": activation_code,
            "license_type": LicenseTypeEnum.ENTERPRISE,
            "max_gpus": 1,
            "expiration_time": datetime.now(timezone.utc) + timedelta(days=365),
            "issuer": "external-api",
            "description": "License from external API",
        }

    # 4. Activate each GPU with corresponding activation code
    activated_gpus = []
    for idx, gpu in enumerate(gpus):
        activation_code = request.activation_code[idx]

        # Check if this GPU is already activated with any license
        existing_gpu_activation = await session.exec(
            select(LicenseActivation).where(LicenseActivation.gpu_sn == gpu.id)
        )
        if existing_gpu_activation.first():
            continue

        # Get license info for this activation code
        license_info = await get_license_info_from_external_api(activation_code)

        # Get or create license
        existing_license = await session.exec(
            select(License).where(License.license_code == license_info["license_code"])
        )
        existing_license = existing_license.first()

        if existing_license:
            # License exists, update if not active
            license = existing_license
            if license.status != LicenseStatusEnum.ACTIVE:
                license.status = LicenseStatusEnum.ACTIVE
                license.activation_time = datetime.now(timezone.utc)
                license.updated_at = datetime.now(timezone.utc)
                session.add(license)
                await session.flush()
        else:
            # Create new license
            license = License(
                license_id=license_info["license_id"],
                license_code=license_info["license_code"],
                license_type=license_info["license_type"],
                status=LicenseStatusEnum.ACTIVE,
                activation_time=datetime.now(timezone.utc),
                expiration_time=license_info["expiration_time"],
                issued_time=datetime.now(timezone.utc),
                issuer=license_info["issuer"],
                max_gpus=license_info["max_gpus"],
                description=license_info["description"],
            )
            session.add(license)
            await session.flush()

        # Create license activation record
        activation = LicenseActivation(
            license_external_id=license_info["license_id"],
            license_code=license_info["license_code"],
            license_id=license.id,
            worker_id=request.worker_id,
            gpu_id=gpu.id,
            gpu_sn=gpu.id,
            gpu_model=gpu.name,
            status=LicenseStatusEnum.ACTIVE,
            activation_time=datetime.now(timezone.utc),
            expiration_time=license_info["expiration_time"],
            activated_by="system",
        )
        session.add(activation)
        await session.flush()
        activated_gpus.append(activation)

        # Record individual license operation
        license_operation = LicenseOperation(
            license_id=license.id,
            operation_type=LicenseOperationTypeEnum.ACTIVATE,
            operator=user.username,
            operation_time=datetime.now(timezone.utc),
            description=f"Activate GPU {gpu.id} with license {license_info['license_id']}",
        )
        session.add(license_operation)

    # 5. Commit all changes at once
    await session.commit()

    # 6. Return result
    return {
        "message": f"Successfully activated {len(activated_gpus)} GPUs",
        "activated_gpus_count": len(activated_gpus),
    }


@router.post("/renew-batch")
async def renew_license_batch(
    request: BatchLicenseRenewalRequest,
    user: CurrentUserDep,
    session: AsyncSession = Depends(get_session),
):
    """
    Batch renew licenses for all GPUs on a worker.
    """
    # 1. Get all activated GPUs on the specified worker
    activated_gpus = await session.exec(
        select(LicenseActivation).where(
            LicenseActivation.worker_id == request.worker_id,
            LicenseActivation.status == LicenseStatusEnum.ACTIVE,
        )
    )
    activated_gpus = activated_gpus.all()
    if not activated_gpus:
        raise HTTPException(
            status_code=400,
            detail=f"No activated GPUs found on worker {request.worker_id}",
        )

    # 2. Check if we have enough activation codes
    if len(request.activation_code) < len(activated_gpus):
        raise HTTPException(status_code=400, detail="Not enough activation codes")

    # 3. Call external API to get license information
    async def get_license_info_from_external_api(activation_code: str):
        """
        Simulate calling external API to get license information.
        """
        # Generate a random string to ensure uniqueness
        random_str = secrets.token_hex(4)
        return {
            "license_id": f"license-{random_str}-{activation_code[:8]}",
            "license_code": activation_code,
            "license_type": LicenseTypeEnum.ENTERPRISE,
            "max_gpus": 1,
            "expiration_time": datetime.now(timezone.utc) + timedelta(days=365),
            "issuer": "external-api",
            "description": "License from external API",
        }

    # 4. Renew each GPU with corresponding activation code
    renewed_gpus_count = 0
    for idx, activation in enumerate(activated_gpus):
        activation_code = request.activation_code[idx]

        # Get the license
        license = await session.get(License, activation.license_id)
        if not license:
            continue

        # Get license info for this activation code
        license_info = await get_license_info_from_external_api(activation_code)

        # Update license expiration time
        license.expiration_time = license_info["expiration_time"]
        session.add(license)

        # Update activation record expiration time
        activation.expiration_time = license_info["expiration_time"]
        session.add(activation)
        renewed_gpus_count += 1

        # Record individual license operation
        license_operation = LicenseOperation(
            license_id=license.id,
            operation_type=LicenseOperationTypeEnum.RENEW,
            operator=user.username,
            operation_time=datetime.now(timezone.utc),
            description=f"Renew GPU {activation.gpu_sn} license",
        )
        session.add(license_operation)

    # 5. Commit all changes at once
    await session.commit()

    # 6. Return result
    return {
        "message": f"Successfully renewed {renewed_gpus_count} GPUs",
        "renewed_gpus_count": renewed_gpus_count,
    }


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


# License Operation Routes


@router.get("/{license_id}/operations", response_model=List[LicenseOperationPublic])
async def list_license_operations_by_license(
    license_id: int,
    operation_type: Optional[LicenseOperationTypeEnum] = None,
    operator: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    List license operations for a specific license.
    """
    # Check if license exists
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    query = select(LicenseOperation).where(LicenseOperation.license_id == license_id)

    if operation_type:
        query = query.where(LicenseOperation.operation_type == operation_type)
    if operator:
        query = query.where(LicenseOperation.operator == operator)
    if start_time:
        query = query.where(LicenseOperation.operation_time >= start_time)
    if end_time:
        query = query.where(LicenseOperation.operation_time <= end_time)

    # Order by operation time descending
    query = query.order_by(LicenseOperation.operation_time.desc())

    result = await session.exec(query)
    return result.all()
