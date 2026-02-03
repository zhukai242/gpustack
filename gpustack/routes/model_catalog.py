from fastapi import APIRouter, Depends, Query
from sqlmodel import select
from typing import List, Optional, Dict, Any
import sqlalchemy as sa

from gpustack.api.exceptions import NotFoundException, AlreadyExistsException
from gpustack.server.deps import SessionDep, get_admin_user
from gpustack.schemas.model_catalog import (
    ModelCatalog,
    ModelCatalogCreate,
    ModelCatalogUpdate,
    ModelCatalogResponse,
    ModelCatalogList,
    ModelCatalogListParams,
    ModelCatalogSpec,
    ModelCatalogSpecCreate,
    ModelCatalogSpecUpdate,
    ModelCatalogSpecResponse,
)
from gpustack.schemas.users import User
from gpustack.schemas.models import Model, ModelInstance, ModelInstanceStateEnum
from gpustack.server.load_services import GPULoadService

router = APIRouter()


@router.post("/", response_model=ModelCatalogResponse, tags=["Model Catalog"])
async def create_model_catalog(
    session: SessionDep,
    model_catalog_data: ModelCatalogCreate,
    current_user: User = Depends(get_admin_user),
):
    """创建模型目录"""
    # 检查模型名称是否已存在
    existing_model_result = await session.exec(
        select(ModelCatalog).where(
            ModelCatalog.name == model_catalog_data.name,
            ModelCatalog.deleted_at.is_(None),
        )
    )
    existing_model = existing_model_result.first()

    if existing_model:
        raise AlreadyExistsException(f"模型 {model_catalog_data.name} 已存在")

    # 创建模型目录（不包含specs，避免类型转换问题）
    model_catalog_data_dict = model_catalog_data.model_dump()
    specs_data = model_catalog_data_dict.pop('specs', [])
    # 设置创建者ID和租户ID
    model_catalog_data_dict['created_by'] = current_user.id
    model_catalog_data_dict['tenant_id'] = current_user.tenant_id
    model_catalog = ModelCatalog(**model_catalog_data_dict)

    # 保存到数据库（先保存模型目录，获取ID）
    session.add(model_catalog)
    await session.commit()
    await session.refresh(model_catalog)

    # 处理规格列表
    for spec_data in specs_data:
        spec = ModelCatalogSpec(**spec_data)
        spec.model_catalog_id = model_catalog.id
        session.add(spec)

    await session.commit()
    await session.refresh(model_catalog)

    # 确保所有字段都被正确加载
    # 重新从数据库中获取完整的模型目录对象，包括specs关系
    # 先await获取结果，然后调用first()方法
    result = await session.exec(
        select(ModelCatalog)
        .options(sa.orm.joinedload(ModelCatalog.specs))
        .where(ModelCatalog.id == model_catalog.id)
    )
    refreshed_model = result.first()
    if not refreshed_model:
        raise NotFoundException(f"模型目录 ID {model_catalog.id} 不存在")

    # 创建响应模型，手动处理specs和创建者信息
    return ModelCatalogResponse(
        id=refreshed_model.id,
        name=refreshed_model.name,
        description=refreshed_model.description,
        home=refreshed_model.home,
        icon=refreshed_model.icon,
        size=refreshed_model.size,
        activated_size=refreshed_model.activated_size,
        size_unit=refreshed_model.size_unit,
        categories=refreshed_model.categories,
        capabilities=refreshed_model.capabilities,
        licenses=refreshed_model.licenses,
        release_date=refreshed_model.release_date,
        is_deployed=refreshed_model.is_deployed,
        created_at=refreshed_model.created_at,
        updated_at=refreshed_model.updated_at,
        deleted_at=refreshed_model.deleted_at,
        created_by=refreshed_model.created_by,
        created_by_username=(
            refreshed_model.creator.username if refreshed_model.creator else None
        ),
        tenant_id=refreshed_model.tenant_id,
        specs=[
            ModelCatalogSpecResponse(
                id=spec.id,
                mode=spec.mode,
                quantization=spec.quantization,
                gpu_filters=spec.gpu_filters,
                source=spec.source,
                huggingface_repo_id=spec.huggingface_repo_id,
                huggingface_filename=spec.huggingface_filename,
                model_scope_model_id=spec.model_scope_model_id,
                model_scope_file_path=spec.model_scope_file_path,
                local_path=spec.local_path,
                backend=spec.backend,
                backend_version=spec.backend_version,
                backend_parameters=spec.backend_parameters,
                env=spec.env,
                created_at=spec.created_at,
                updated_at=spec.updated_at,
                deleted_at=spec.deleted_at,
            )
            for spec in refreshed_model.specs
        ],
    )


@router.get("/", response_model=ModelCatalogList, tags=["Model Catalog"])
async def list_model_catalog(
    session: SessionDep,
    params: ModelCatalogListParams = Depends(),
    is_deployed: Optional[bool] = Query(None, description="是否已部署"),
    category: Optional[str] = Query(None, description="模型类别"),
    current_user: User = Depends(get_admin_user),
):
    """获取模型目录列表"""
    # 在查询时预加载specs和creator关系，避免延迟加载导致的MissingGreenlet错误
    # 只返回当前租户的模型
    query = (
        select(ModelCatalog)
        .options(
            sa.orm.joinedload(ModelCatalog.specs),
            sa.orm.joinedload(ModelCatalog.creator),
        )
        .where(
            ModelCatalog.deleted_at.is_(None),
            ModelCatalog.tenant_id == current_user.tenant_id,
        )
    )

    # 应用过滤条件
    if is_deployed is not None:
        query = query.where(ModelCatalog.is_deployed == is_deployed)

    if category:
        # 使用PostgreSQL的JSONB操作符查询数组包含关系
        # 直接使用SQLAlchemy的操作符构建查询
        from sqlalchemy.dialects.postgresql import JSONB

        # 使用@>操作符检查JSONB数组包含关系
        query = query.where(
            ModelCatalog.categories.op('@>')(sa.cast([category], JSONB))
        )

    # 应用排序
    if params.sort_by:
        query = query.order_by(
            getattr(ModelCatalog, params.sort_by, ModelCatalog.created_at)
        )
    else:
        query = query.order_by(ModelCatalog.created_at.desc())

    # 应用分页
    # 获取总记录数
    count_query = select(sa.func.count(ModelCatalog.id))
    count_query = count_query.where(ModelCatalog.deleted_at.is_(None))
    count_query = count_query.where(ModelCatalog.tenant_id == current_user.tenant_id)

    # 应用相同的category过滤条件
    if category:
        from sqlalchemy.dialects.postgresql import JSONB

        count_query = count_query.where(
            ModelCatalog.categories.op('@>')(sa.cast([category], JSONB))
        )

    count_result = await session.exec(count_query)
    total = count_result.one()

    offset = (params.page - 1) * params.perPage
    result = await session.exec(query.offset(offset).limit(params.perPage))
    # 使用unique()方法去重，因为joinedload加载集合关系会导致重复的父对象
    items = result.unique().all()

    # 计算总页数
    total_page = (total + params.perPage - 1) // params.perPage

    # 构建响应模型列表，确保created_by_username字段被正确设置
    response_items = []
    for item in items:
        # 手动构建ModelCatalogResponse对象
        response_item = ModelCatalogResponse(
            id=item.id,
            name=item.name,
            description=item.description,
            home=item.home,
            icon=item.icon,
            size=item.size,
            activated_size=item.activated_size,
            size_unit=item.size_unit,
            categories=item.categories,
            capabilities=item.capabilities,
            licenses=item.licenses,
            release_date=item.release_date,
            is_deployed=item.is_deployed,
            created_at=item.created_at,
            updated_at=item.updated_at,
            deleted_at=item.deleted_at,
            created_by=item.created_by,
            created_by_username=item.creator.username if item.creator else None,
            tenant_id=item.tenant_id,
            specs=[
                ModelCatalogSpecResponse(
                    id=spec.id,
                    mode=spec.mode,
                    quantization=spec.quantization,
                    gpu_filters=spec.gpu_filters,
                    source=spec.source,
                    huggingface_repo_id=spec.huggingface_repo_id,
                    huggingface_filename=spec.huggingface_filename,
                    model_scope_model_id=spec.model_scope_model_id,
                    model_scope_file_path=spec.model_scope_file_path,
                    local_path=spec.local_path,
                    backend=spec.backend,
                    backend_version=spec.backend_version,
                    backend_parameters=spec.backend_parameters,
                    env=spec.env,
                    created_at=spec.created_at,
                    updated_at=spec.updated_at,
                    deleted_at=spec.deleted_at,
                )
                for spec in item.specs
            ],
        )
        response_items.append(response_item)

    return ModelCatalogList(
        items=response_items,
        pagination={
            "page": params.page,
            "perPage": params.perPage,
            "total": total,
            "totalPage": total_page,
        },
    )


@router.get("/stats", tags=["Model Catalog"])
async def get_model_catalog_stats(
    session: SessionDep,
    current_user: User = Depends(get_admin_user),
):
    """获取模型目录统计信息"""
    # 1. 统计当前租户的模型总数
    total_count_result = await session.exec(
        select(sa.func.count(ModelCatalog.id))
        .where(ModelCatalog.deleted_at.is_(None))
        .where(ModelCatalog.tenant_id == current_user.tenant_id)
    )
    total_count = total_count_result.one()

    # 2. 按照类型统计模型数量
    # 注意：categories是一个JSON数组字段，需要使用unnest或json_array_elements函数
    # 这里使用一个简化的方法，直接查询当前租户的模型，然后在Python中统计
    all_models_result = await session.exec(
        select(ModelCatalog).where(
            ModelCatalog.deleted_at.is_(None),
            ModelCatalog.tenant_id == current_user.tenant_id,
        )
    )
    all_models = all_models_result.all()

    category_stats = {}
    for model in all_models:
        if model.categories:
            for category in model.categories:
                if category in category_stats:
                    category_stats[category] += 1
                else:
                    category_stats[category] = 1

    # 3. 本月新增的模型数量
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc)
    start_of_month = datetime(today.year, today.month, 1, tzinfo=timezone.utc)

    monthly_count_result = await session.exec(
        select(sa.func.count(ModelCatalog.id))
        .where(ModelCatalog.deleted_at.is_(None))
        .where(ModelCatalog.created_at >= start_of_month)
        .where(ModelCatalog.tenant_id == current_user.tenant_id)
    )
    monthly_count = monthly_count_result.one()

    # 4. 按月统计模型的增长趋势
    # 提取所有模型的创建时间，按月份分组
    growth_trend = {}
    for model in all_models:
        if model.created_at:
            # 获取创建时间的年月
            month_key = model.created_at.strftime("%Y-%m")
            if month_key in growth_trend:
                growth_trend[month_key] += 1
            else:
                growth_trend[month_key] = 1

    # 对增长趋势按月份排序
    sorted_growth_trend = dict(sorted(growth_trend.items()))

    return {
        "total_count": total_count,
        "category_stats": category_stats,
        "monthly_count": monthly_count,
        "growth_trend": sorted_growth_trend,
    }


async def _get_model_catalogs(
    session: SessionDep, tenant_id: int
) -> List[ModelCatalog]:
    """
    查询当前租户的所有模型目录，预加载specs关系

    Args:
        session: 数据库会话
        tenant_id: 租户ID

    Returns:
        模型目录列表
    """
    model_catalogs = await session.exec(
        select(ModelCatalog)
        .options(sa.orm.joinedload(ModelCatalog.specs))
        .where(
            ModelCatalog.deleted_at.is_(None),
            ModelCatalog.tenant_id == tenant_id,
        )
    )
    return model_catalogs.unique().all()


async def _get_running_instances(session: SessionDep) -> List[ModelInstance]:
    """
    查询所有运行中的模型实例

    Args:
        session: 数据库会话

    Returns:
        运行中的模型实例列表
    """
    running_instances = await session.exec(
        select(ModelInstance).where(
            ModelInstance.state == ModelInstanceStateEnum.RUNNING
        )
    )
    return running_instances.all()


async def _get_model_by_id(session: SessionDep, model_id: int) -> Optional[Model]:
    """
    根据ID获取模型信息

    Args:
        session: 数据库会话
        model_id: 模型ID

    Returns:
        模型实例，如果不存在则返回None
    """
    model = await session.exec(select(Model).where(Model.id == model_id))
    return model.first()


async def _find_corresponding_catalog(
    model_catalog_list: List[ModelCatalog], model: Model
) -> Optional[ModelCatalog]:
    """
    查找与模型对应的模型目录

    Args:
        model_catalog_list: 模型目录列表
        model: 模型实例

    Returns:
        对应的模型目录，如果不存在则返回None
    """
    for catalog in model_catalog_list:
        # 检查路径是否匹配
        if hasattr(catalog, 'specs'):
            for spec in catalog.specs:
                if spec.local_path == model.local_path:
                    return catalog
    return None


async def _build_instance_info(instance: ModelInstance) -> Dict[str, Any]:
    """
    构建实例基本信息

    Args:
        instance: 模型实例

    Returns:
        实例信息字典
    """
    return {
        "id": instance.id,
        "name": instance.name,
        "worker_id": instance.worker_id,
        "worker_name": instance.worker_name,
        "worker_ip": instance.worker_ip,
        "port": instance.port,
        "ports": instance.ports,
        "resolved_path": instance.resolved_path,
        "state": instance.state,
        "state_message": instance.state_message,
        "created_at": instance.created_at,
        "updated_at": instance.updated_at,
    }


async def _build_gpu_stats(
    session: SessionDep, instance: ModelInstance
) -> List[Dict[str, Any]]:
    """
    构建GPU消耗情况

    Args:
        session: 数据库会话
        instance: 模型实例

    Returns:
        GPU消耗情况列表
    """
    gpu_stats = []
    if instance.gpu_indexes and instance.computed_resource_claim and instance.worker_id:
        from datetime import datetime, timezone

        current_time = datetime.now(timezone.utc)
        start_time = instance.updated_at
        # 计算持续时间（秒）
        duration = None
        if start_time:
            duration = (current_time - start_time).total_seconds()

        for gpu_index in instance.gpu_indexes:
            # 获取GPU负载时间序列数据
            gpu_load_service = GPULoadService(session)
            # 获取最近的GPU负载数据
            gpu_loads = await gpu_load_service.get_by_gpu_index(
                instance.worker_id, gpu_index, limit=100
            )

            # 提取时间序列数据
            time_series = []
            for load in gpu_loads:
                # 检查timestamp类型，确保可以调用isoformat()
                timestamp_str = None
                if hasattr(load.timestamp, 'isoformat'):
                    timestamp_str = load.timestamp.isoformat()
                elif isinstance(load.timestamp, (int, float)):
                    # 如果是时间戳整数，转换为datetime对象后再调用isoformat()
                    from datetime import datetime, timezone

                    timestamp_str = datetime.fromtimestamp(
                        load.timestamp, timezone.utc
                    ).isoformat()
                else:
                    timestamp_str = str(load.timestamp)

                time_series.append(
                    {
                        "timestamp": timestamp_str,
                        "gpu_utilization": load.gpu_utilization,
                        "vram_utilization": load.vram_utilization,
                    }
                )

            gpu_stat = {
                "worker_id": instance.worker_id,
                "worker_name": instance.worker_name,
                "gpu_index": gpu_index,
                "gpu_type": instance.gpu_type,
                "computed_resource_claim": (
                    instance.computed_resource_claim.model_dump()
                ),
                "time_info": {
                    "start_time": (
                        start_time.isoformat()
                        if (start_time and hasattr(start_time, 'isoformat'))
                        else str(start_time) if start_time else None
                    ),
                    "end_time": (
                        current_time.isoformat()
                        if hasattr(current_time, 'isoformat')
                        else str(current_time)
                    ),
                    "duration_seconds": duration,
                },
                "time_series": time_series,
            }
            gpu_stats.append(gpu_stat)
    return gpu_stats


async def _build_model_info(
    model: Model,
    corresponding_catalog: ModelCatalog,
    instances_info: List[Dict[str, Any]],
    gpu_stats: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    构建模型信息

    Args:
        model: 模型实例
        corresponding_catalog: 对应的模型目录
        instances_info: 实例信息列表
        gpu_stats: GPU消耗情况列表

    Returns:
        模型信息字典
    """
    return {
        "model_catalog": {
            "id": corresponding_catalog.id,
            "name": corresponding_catalog.name,
            "description": corresponding_catalog.description,
            "home": corresponding_catalog.home,
            "icon": corresponding_catalog.icon,
            "size": corresponding_catalog.size,
            "activated_size": corresponding_catalog.activated_size,
            "size_unit": corresponding_catalog.size_unit,
            "categories": corresponding_catalog.categories,
            "capabilities": corresponding_catalog.capabilities,
            "licenses": corresponding_catalog.licenses,
            "release_date": corresponding_catalog.release_date,
            "is_deployed": corresponding_catalog.is_deployed,
            "created_at": corresponding_catalog.created_at,
            "updated_at": corresponding_catalog.updated_at,
            "created_by": corresponding_catalog.created_by,
            "tenant_id": corresponding_catalog.tenant_id,
        },
        "model": {
            "id": model.id,
            "name": model.name,
            "source": model.source,
            "local_path": model.local_path,
            "huggingface_repo_id": model.huggingface_repo_id,
            "model_scope_model_id": model.model_scope_model_id,
            "replicas": model.replicas,
            "ready_replicas": model.ready_replicas,
            "backend": model.backend,
            "backend_version": model.backend_version,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        },
        "instances": instances_info,
        "gpu_stats": gpu_stats,
    }


@router.get("/running-models", tags=["Model Catalog"])
async def get_running_models(
    session: SessionDep,
    current_user: User = Depends(get_admin_user),
):
    """获取当前正在运行的模型及其实例信息和GPU消耗情况"""
    # 查询当前租户的所有模型目录，预加载specs关系
    model_catalog_list = await _get_model_catalogs(session, current_user.tenant_id)

    # 查询所有运行中的模型实例
    running_instances_list = await _get_running_instances(session)

    # 按模型分组实例
    instances_by_model = {}
    for instance in running_instances_list:
        if instance.model_id not in instances_by_model:
            instances_by_model[instance.model_id] = []
        instances_by_model[instance.model_id].append(instance)

    # 获取每个模型的信息
    running_models = []
    for model_id, instances in instances_by_model.items():
        # 获取模型信息
        model = await _get_model_by_id(session, model_id)
        if not model:
            continue

        # 查找对应的模型目录
        corresponding_catalog = await _find_corresponding_catalog(
            model_catalog_list, model
        )
        if not corresponding_catalog:
            continue

        # 收集实例信息和GPU消耗情况
        instances_info = []
        gpu_stats = []

        for instance in instances:
            # 实例基本信息
            instance_info = await _build_instance_info(instance)
            instances_info.append(instance_info)

            # GPU消耗情况
            instance_gpu_stats = await _build_gpu_stats(session, instance)
            gpu_stats.extend(instance_gpu_stats)

        # 构建模型信息
        model_info = await _build_model_info(
            model, corresponding_catalog, instances_info, gpu_stats
        )
        running_models.append(model_info)

    return {"running_models": running_models}


@router.get(
    "/{model_catalog_id}",
    response_model=ModelCatalogResponse,
    tags=["Model Catalog"],
)
async def get_model_catalog(
    session: SessionDep,
    model_catalog_id: int,
    current_user: User = Depends(get_admin_user),
):
    """获取单个模型目录详情"""
    # 预加载specs和creator关系，避免延迟加载导致的MissingGreenlet错误
    # 只返回当前租户的模型
    result = await session.exec(
        select(ModelCatalog)
        .options(
            sa.orm.joinedload(ModelCatalog.specs),
            sa.orm.joinedload(ModelCatalog.creator),
        )
        .where(
            ModelCatalog.id == model_catalog_id,
            ModelCatalog.tenant_id == current_user.tenant_id,
        )
    )
    model_catalog = result.first()

    if not model_catalog or model_catalog.deleted_at:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    return model_catalog


@router.put(
    "/{model_catalog_id}",
    response_model=ModelCatalogResponse,
    tags=["Model Catalog"],
)
async def update_model_catalog(
    session: SessionDep,
    model_catalog_id: int,
    model_catalog_data: ModelCatalogUpdate,
    current_user: User = Depends(get_admin_user),
):
    """更新模型目录"""
    # 只更新当前租户的模型
    model_catalog = await session.exec(
        select(ModelCatalog).where(
            ModelCatalog.id == model_catalog_id,
            ModelCatalog.tenant_id == current_user.tenant_id,
            ModelCatalog.deleted_at.is_(None),
        )
    ).first()

    if not model_catalog:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    # 更新模型目录字段
    update_data = model_catalog_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(model_catalog, field, value)

    session.commit()
    session.refresh(model_catalog)

    return model_catalog


@router.delete("/{model_catalog_id}", tags=["Model Catalog"])
async def delete_model_catalog(
    session: SessionDep,
    model_catalog_id: int,
    current_user: User = Depends(get_admin_user),
):
    """删除模型目录"""
    # 只删除当前租户的模型
    model_catalog = await session.exec(
        select(ModelCatalog).where(
            ModelCatalog.id == model_catalog_id,
            ModelCatalog.tenant_id == current_user.tenant_id,
            ModelCatalog.deleted_at.is_(None),
        )
    ).first()

    if not model_catalog:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    # 软删除模型目录
    model_catalog.soft_delete(session)

    session.commit()

    return {"message": f"模型目录 ID {model_catalog_id} 已删除"}


@router.post(
    "/{model_catalog_id}/specs",
    response_model=ModelCatalogSpecResponse,
    tags=["Model Catalog"],
)
async def create_model_catalog_spec(
    session: SessionDep,
    model_catalog_id: int,
    spec_data: ModelCatalogSpecCreate,
    current_user: User = Depends(get_admin_user),
):
    """为模型目录创建规格"""
    # 检查模型目录是否存在，且属于当前租户
    model_catalog = await session.exec(
        select(ModelCatalog).where(
            ModelCatalog.id == model_catalog_id,
            ModelCatalog.tenant_id == current_user.tenant_id,
            ModelCatalog.deleted_at.is_(None),
        )
    ).first()

    if not model_catalog:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    # 创建规格
    spec = ModelCatalogSpec.model_validate(spec_data)
    spec.model_catalog_id = model_catalog_id

    session.add(spec)
    await session.commit()
    await session.refresh(spec)

    return spec


@router.get(
    "/{model_catalog_id}/specs",
    response_model=List[ModelCatalogSpecResponse],
    tags=["Model Catalog"],
)
async def list_model_catalog_specs(
    session: SessionDep,
    model_catalog_id: int,
    current_user: User = Depends(get_admin_user),
):
    """获取模型目录的所有规格"""
    # 检查模型目录是否存在，且属于当前租户
    model_catalog = await session.exec(
        select(ModelCatalog).where(
            ModelCatalog.id == model_catalog_id,
            ModelCatalog.tenant_id == current_user.tenant_id,
            ModelCatalog.deleted_at.is_(None),
        )
    ).first()

    if not model_catalog:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    # 获取规格列表
    specs_result = await session.exec(
        select(ModelCatalogSpec).where(
            ModelCatalogSpec.model_catalog_id == model_catalog_id,
            ModelCatalogSpec.deleted_at.is_(None),
        )
    )
    specs = specs_result.all()

    return specs


@router.get(
    "/specs/{spec_id}",
    response_model=ModelCatalogSpecResponse,
    tags=["Model Catalog"],
)
async def get_model_catalog_spec(
    session: SessionDep, spec_id: int, current_user: User = Depends(get_admin_user)
):
    """获取单个模型目录规格详情"""
    # 只返回当前租户的模型规格
    result = await session.exec(
        select(ModelCatalogSpec)
        .join(ModelCatalog)
        .where(
            ModelCatalogSpec.id == spec_id,
            ModelCatalogSpec.deleted_at.is_(None),
            ModelCatalog.tenant_id == current_user.tenant_id,
        )
    )
    spec = result.first()

    if not spec:
        raise NotFoundException(f"模型目录规格 ID {spec_id} 不存在")

    return spec


@router.put(
    "/specs/{spec_id}",
    response_model=ModelCatalogSpecResponse,
    tags=["Model Catalog"],
)
async def update_model_catalog_spec(
    session: SessionDep,
    spec_id: int,
    spec_data: ModelCatalogSpecUpdate,
    current_user: User = Depends(get_admin_user),
):
    """更新模型目录规格"""
    # 只更新当前租户的模型规格
    spec = await session.exec(
        select(ModelCatalogSpec)
        .join(ModelCatalog)
        .where(
            ModelCatalogSpec.id == spec_id,
            ModelCatalogSpec.deleted_at.is_(None),
            ModelCatalog.tenant_id == current_user.tenant_id,
        )
    ).first()

    if not spec:
        raise NotFoundException(f"模型目录规格 ID {spec_id} 不存在")

    # 更新规格字段
    update_data = spec_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(spec, field, value)

    session.commit()
    session.refresh(spec)

    return spec


@router.delete("/specs/{spec_id}", tags=["Model Catalog"])
async def delete_model_catalog_spec(
    session: SessionDep, spec_id: int, current_user: User = Depends(get_admin_user)
):
    """删除模型目录规格"""
    # 只删除当前租户的模型规格
    spec = await session.exec(
        select(ModelCatalogSpec)
        .join(ModelCatalog)
        .where(
            ModelCatalogSpec.id == spec_id,
            ModelCatalogSpec.deleted_at.is_(None),
            ModelCatalog.tenant_id == current_user.tenant_id,
        )
    ).first()

    if not spec:
        raise NotFoundException(f"模型目录规格 ID {spec_id} 不存在")

    # 软删除规格
    spec.soft_delete(session)

    session.commit()

    return {"message": f"模型目录规格 ID {spec_id} 已删除"}
