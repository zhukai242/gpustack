from datetime import datetime, timezone
from typing import List, Optional, Dict
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from gpustack.server.deps import SessionDep, CurrentUserDep
from gpustack.schemas.models import (
    Model,
    ModelInstance,
    ModelInstanceStateEnum,
)
from gpustack.schemas.users import User
from gpustack.server.load_services import GPULoadService

router = APIRouter(tags=["Tasks"])


class TaskStatsResponse(BaseModel):
    """任务统计响应"""

    total: int
    running: int
    pending: int
    error: int
    other: int


class TaskInfoResponse(BaseModel):
    """任务信息响应"""

    id: int
    name: str
    model_name: str
    group: str
    type: str
    status: ModelInstanceStateEnum
    queue_position: Optional[int] = None
    queue_time: Optional[int] = None  # 秒
    uptime: Optional[int] = None  # 秒
    username: Optional[str] = None
    # 实际使用量
    actual_gpu_utilization: Optional[float] = None  # 实际GPU使用率（多张卡的平均值）
    actual_vram_utilization: Optional[float] = None  # 实际VRAM使用率（多张卡的平均值）
    # 预计使用量
    estimated_vram_usage: Optional[Dict[int, int]] = (
        None  # 预计VRAM使用量（从computed_resource_claim获取）
    )


class ResourceUsageResponse(BaseModel):
    """资源使用响应"""

    time: str
    gpu_utilization: float
    vram_usage: float


class TaskListResponse(BaseModel):
    """任务列表响应"""

    items: List[TaskInfoResponse]
    total: int


class ResourceUsageStatsResponse(BaseModel):
    """资源使用统计响应"""

    model_name: str
    usage_data: List[ResourceUsageResponse]


@router.get("/stats", response_model=TaskStatsResponse)
async def get_task_stats(
    session: SessionDep,
    current_user: CurrentUserDep,
):
    """获取任务统计信息，包括总数、运行中、排队中等状态的个数"""
    # 查询当前租户下的所有模型ID
    model_ids_result = await session.exec(
        select(Model.id)
        .join(User, Model.created_by == User.id)
        .where(User.tenant_id == current_user.tenant_id)
    )
    model_ids = model_ids_result.all()

    if not model_ids:
        return TaskStatsResponse(total=0, running=0, pending=0, error=0, other=0)

    # 查询任务总数
    total_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids)
        )
    )
    total = total_result.one() or 0

    # 查询运行中的任务数
    running_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids),
            ModelInstance.state == ModelInstanceStateEnum.RUNNING,
        )
    )
    running = running_result.one() or 0

    # 查询排队中的任务数
    pending_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids),
            ModelInstance.state == ModelInstanceStateEnum.PENDING,
        )
    )
    pending = pending_result.one() or 0

    # 查询错误状态的任务数
    error_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids),
            ModelInstance.state == ModelInstanceStateEnum.ERROR,
        )
    )
    error = error_result.one() or 0

    # 计算其他状态的任务数
    other = total - running - pending - error

    return TaskStatsResponse(
        total=total, running=running, pending=pending, error=error, other=other
    )


@router.get("/train/stats", response_model=TaskStatsResponse)
async def get_train_task_stats(
    session: SessionDep,
    current_user: CurrentUserDep,
):
    """获取训练任务统计信息，包括总数、运行中、排队中等状态的个数"""
    # 查询当前用户创建的所有训练模型ID
    model_ids_result = await session.exec(
        select(Model.id).where(
            Model.created_by == current_user.id, Model.task_type == 1  # 只查询训练任务
        )
    )
    model_ids = model_ids_result.all()

    if not model_ids:
        return TaskStatsResponse(total=0, running=0, pending=0, error=0, other=0)

    # 查询任务总数
    total_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids)
        )
    )
    total = total_result.one() or 0

    # 查询运行中的任务数
    running_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids),
            ModelInstance.state == ModelInstanceStateEnum.RUNNING,
        )
    )
    running = running_result.one() or 0

    # 查询排队中的任务数
    pending_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids),
            ModelInstance.state == ModelInstanceStateEnum.PENDING,
        )
    )
    pending = pending_result.one() or 0

    # 查询错误状态的任务数
    error_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids),
            ModelInstance.state == ModelInstanceStateEnum.ERROR,
        )
    )
    error = error_result.one() or 0

    # 计算其他状态的任务数
    other = total - running - pending - error

    return TaskStatsResponse(
        total=total, running=running, pending=pending, error=error, other=other
    )


async def _get_model_ids(
    session: SessionDep, current_user: CurrentUserDep
) -> List[int]:
    """
    查询当前租户下的所有模型ID

    Args:
        session: 数据库会话
        current_user: 当前用户

    Returns:
        模型ID列表
    """
    model_ids_result = await session.exec(
        select(Model.id)
        .join(User, Model.created_by == User.id)
        .where(User.tenant_id == current_user.tenant_id)
    )
    return model_ids_result.all()


async def _get_train_model_ids(
    session: SessionDep, current_user: CurrentUserDep
) -> List[int]:
    """
    查询当前用户创建的所有训练模型ID

    Args:
        session: 数据库会话
        current_user: 当前用户

    Returns:
        训练模型ID列表
    """
    model_ids_result = await session.exec(
        select(Model.id).where(
            Model.created_by == current_user.id, Model.task_type == 1  # 只查询训练任务
        )
    )
    return model_ids_result.all()


async def _get_pending_instance_ids(
    session: SessionDep, model_ids: List[int]
) -> Dict[int, int]:
    """
    获取排队中的任务及其位置

    Args:
        session: 数据库会话
        model_ids: 模型ID列表

    Returns:
        任务ID到队列位置的映射
    """
    pending_instances_result = await session.exec(
        select(ModelInstance)
        .where(
            ModelInstance.model_id.in_(model_ids),
            ModelInstance.state == ModelInstanceStateEnum.PENDING,
        )
        .order_by(ModelInstance.created_at)
    )
    pending_instances = pending_instances_result.all()
    return {instance.id: idx + 1 for idx, instance in enumerate(pending_instances)}


async def _build_task_info(
    session: SessionDep, instance: ModelInstance, pending_instance_ids: Dict[int, int]
) -> TaskInfoResponse:
    """
    构建单个任务的信息

    Args:
        session: 数据库会话
        instance: 模型实例
        pending_instance_ids: 任务ID到队列位置的映射

    Returns:
        任务信息响应
    """
    # 获取模型信息
    model_result = await session.exec(
        select(Model).where(Model.id == instance.model_id)
    )
    model = model_result.one_or_none()

    # 获取创建者信息
    creator = None
    if model and model.created_by:
        creator_result = await session.exec(
            select(User).where(User.id == model.created_by)
        )
        creator = creator_result.one_or_none()

    # 计算队列时间或运行时间
    queue_time = None
    uptime = None
    current_time = datetime.now(timezone.utc)
    if instance.state == ModelInstanceStateEnum.PENDING:
        # 计算排队时间
        queue_time = int((current_time - instance.created_at).total_seconds())
    elif instance.state == ModelInstanceStateEnum.RUNNING:
        # 计算运行时间
        uptime = int((current_time - instance.created_at).total_seconds())

    # 获取GPU使用情况
    actual_gpu_utilization = None
    actual_vram_utilization = None
    estimated_vram_usage = None
    if instance.state == ModelInstanceStateEnum.RUNNING:
        # 从GPU负载服务获取实时数据
        gpu_load_service = GPULoadService(session)

        # 计算多张卡的平均使用率
        total_gpu_util = 0.0
        total_vram_util = 0.0
        valid_gpu_count = 0

        # 只通过gpu_indexes和worker_id获取GPU信息
        if instance.gpu_indexes and instance.worker_id:
            for gpu_index in instance.gpu_indexes:
                try:
                    # 查询该GPU的最新负载数据
                    gpu_loads = await gpu_load_service.get_by_gpu_index(
                        instance.worker_id, gpu_index, limit=1
                    )
                    if gpu_loads and gpu_loads[0].gpu_utilization is not None:
                        total_gpu_util += gpu_loads[0].gpu_utilization
                        valid_gpu_count += 1
                        if gpu_loads[0].vram_utilization is not None:
                            total_vram_util += gpu_loads[0].vram_utilization
                except Exception:
                    # 忽略单个GPU查询失败的情况，继续处理其他GPU
                    pass

        # 计算平均值
        if valid_gpu_count > 0:
            actual_gpu_utilization = round(total_gpu_util / valid_gpu_count, 2)
            if total_vram_util > 0:
                actual_vram_utilization = round(total_vram_util / valid_gpu_count, 2)

        # 从computed_resource_claim获取预计VRAM使用量
        if instance.computed_resource_claim:
            estimated_vram_usage = instance.computed_resource_claim.vram

    # 确定任务类型
    task_type = "inference"  # 默认值
    if model:
        task_type = "training" if model.task_type == 1 else "inference"

    # 构建任务信息
    return TaskInfoResponse(
        id=instance.id,
        name=instance.name,
        model_name=instance.model_name,
        group=creator.username if creator else "",
        type=task_type,
        status=instance.state,
        queue_position=pending_instance_ids.get(instance.id),
        queue_time=queue_time,
        uptime=uptime,
        username=creator.username if creator else None,
        # 实际使用量
        actual_gpu_utilization=actual_gpu_utilization,
        actual_vram_utilization=actual_vram_utilization,
        # 预计使用量
        estimated_vram_usage=estimated_vram_usage,
    )


@router.get("/list", response_model=TaskListResponse)
async def get_task_list(
    session: SessionDep,
    current_user: CurrentUserDep,
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(10, ge=1, le=100, description="每页数量"),
):
    """获取任务列表，包括部署名称、所属组、类型、状态等信息"""
    # 查询当前租户下的所有模型ID
    model_ids = await _get_model_ids(session, current_user)

    if not model_ids:
        return TaskListResponse(items=[], total=0)

    # 查询所有模型实例
    statement = (
        select(ModelInstance)
        .where(ModelInstance.model_id.in_(model_ids))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    instances_result = await session.exec(statement)
    instances = instances_result.all()

    # 查询总数
    total_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids)
        )
    )
    total = total_result.one() or 0

    # 获取排队中的任务，用于计算队列位置
    pending_instance_ids = await _get_pending_instance_ids(session, model_ids)

    # 构建响应
    items = []
    for instance in instances:
        task_info = await _build_task_info(session, instance, pending_instance_ids)
        items.append(task_info)

    return TaskListResponse(items=items, total=total)


@router.get("/train/list", response_model=TaskListResponse)
async def get_train_task_list(
    session: SessionDep,
    current_user: CurrentUserDep,
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(10, ge=1, le=100, description="每页数量"),
):
    """获取训练任务列表，包括部署名称、所属组、类型、状态等信息"""
    # 查询当前用户创建的所有训练模型ID
    model_ids = await _get_train_model_ids(session, current_user)

    if not model_ids:
        return TaskListResponse(items=[], total=0)

    # 查询所有模型实例
    statement = (
        select(ModelInstance)
        .where(ModelInstance.model_id.in_(model_ids))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    instances_result = await session.exec(statement)
    instances = instances_result.all()

    # 查询总数
    total_result = await session.exec(
        select(func.count(ModelInstance.id)).where(
            ModelInstance.model_id.in_(model_ids)
        )
    )
    total = total_result.one() or 0

    # 获取排队中的任务，用于计算队列位置
    pending_instance_ids = await _get_pending_instance_ids(session, model_ids)

    # 构建响应
    items = []
    for instance in instances:
        task_info = await _build_task_info(session, instance, pending_instance_ids)
        items.append(task_info)

    return TaskListResponse(items=items, total=total)


@router.get("/resource-usage", response_model=List[ResourceUsageStatsResponse])
async def get_resource_usage_stats(
    session: SessionDep,
    current_user: CurrentUserDep,
    hours: int = Query(24, ge=1, le=168, description="统计小时数"),
):
    """获取当前运行中模型的资源使用统计，按时间维度"""
    # 查询当前租户下的所有模型ID
    model_ids_result = await session.exec(
        select(Model.id)
        .join(User, Model.created_by == User.id)
        .where(User.tenant_id == current_user.tenant_id)
    )
    model_ids = model_ids_result.all()

    if not model_ids:
        return []

    # 查询当前运行中的模型实例
    running_instances_result = await session.exec(
        select(ModelInstance).where(
            ModelInstance.model_id.in_(model_ids),
            ModelInstance.state == ModelInstanceStateEnum.RUNNING,
        )
    )
    running_instances = running_instances_result.all()

    # 构建响应
    stats = []
    for instance in running_instances:
        # 获取模型信息
        model_result = await session.exec(
            select(Model).where(Model.id == instance.model_id)
        )
        model = model_result.one_or_none()

        if not model:
            continue

        # 从GPU负载服务获取历史数据
        usage_data = []
        gpu_load_service = GPULoadService(session)

        # 计算时间范围
        from datetime import timedelta

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)
        start_timestamp = int(start_time.timestamp())
        end_timestamp = int(end_time.timestamp())

        # 按时间间隔获取数据（每小时一个数据点）
        interval = 3600  # 1小时
        current_timestamp = start_timestamp

        while current_timestamp <= end_timestamp:
            # 计算该时间点的GPU使用率平均值
            total_gpu_util = 0.0
            total_vram_util = 0.0
            valid_gpu_count = 0

            # 从instance.gpu_indexes和worker_id获取GPU信息
            if instance.gpu_indexes and instance.worker_id:
                for gpu_index in instance.gpu_indexes:
                    try:
                        # 查询该GPU在该时间点附近的负载数据
                        gpu_loads = await gpu_load_service.get_by_gpu_index(
                            instance.worker_id, gpu_index, limit=100
                        )

                        # 找到最接近current_timestamp的数据点
                        closest_load = None
                        min_time_diff = float('inf')

                        for load in gpu_loads:
                            time_diff = abs(load.timestamp - current_timestamp)
                            if time_diff < min_time_diff:
                                min_time_diff = time_diff
                                closest_load = load

                        # 如果找到有效的数据点
                        if closest_load and closest_load.gpu_utilization is not None:
                            total_gpu_util += closest_load.gpu_utilization
                            valid_gpu_count += 1
                            if closest_load.vram_utilization is not None:
                                total_vram_util += closest_load.vram_utilization
                    except Exception:
                        # 忽略单个GPU查询失败的情况，继续处理其他GPU
                        pass

            # 计算平均值
            if valid_gpu_count > 0:
                avg_gpu_util = round(total_gpu_util / valid_gpu_count, 2)
                avg_vram_util = (
                    round(total_vram_util / valid_gpu_count, 2)
                    if total_vram_util > 0
                    else 0.0
                )

                # 添加到使用数据列表
                time_point = datetime.fromtimestamp(current_timestamp, timezone.utc)
                usage_data.append(
                    ResourceUsageResponse(
                        time=time_point.isoformat(),
                        gpu_utilization=avg_gpu_util,
                        vram_usage=avg_vram_util,
                    )
                )

            # 移动到下一个时间点
            current_timestamp += interval

        stats.append(
            ResourceUsageStatsResponse(
                model_name=instance.model_name,
                usage_data=usage_data,
            )
        )

    return stats
