import logging
import math
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from urllib.parse import urlencode
from gpustack_runtime.detector import ManufacturerEnum
from sqlalchemy.orm import selectinload
from sqlmodel import and_, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession
from enum import Enum

from gpustack.api.exceptions import (
    AlreadyExistsException,
    InternalServerErrorException,
    NotFoundException,
    BadRequestException,
)
from gpustack.schemas.common import Pagination
from gpustack.schemas.inference_backend import is_custom_backend
from gpustack.schemas.models import (
    ModelInstance,
    ModelInstancesPublic,
    BackendEnum,
    ModelListParams,
)
from gpustack.schemas.clusters import Cluster
from gpustack.schemas.workers import GPUDeviceStatus, Worker
from gpustack.server.deps import ListParamsDep, SessionDep, CurrentUserDep
from gpustack.schemas.models import (
    Model,
    ModelCreate,
    ModelUpdate,
    ModelPublic,
    ModelPublicWithInstances,
    ModelsPublic,
    ModelsPublicWithInstances,
)
from gpustack.schemas.users import User
from gpustack.schemas.model_routes import (
    ModelRoute,
    ModelRouteTarget,
    TargetStateEnum,
)
from gpustack.schemas.model_catalog import ModelCatalog
from gpustack.server.services import (
    ModelService,
    WorkerService,
    delete_accessible_model_cache,
)
from gpustack.utils.command import find_parameter
from gpustack.utils.convert import safe_int
from gpustack.utils.gpu import parse_gpu_id
from gpustack.routes.model_common import (
    build_category_conditions,
    categories_filter,
)
from gpustack.config.config import get_global_config
from gpustack.utils.grafana import resolve_grafana_base_url

router = APIRouter()

logger = logging.getLogger(__name__)


class ModelStateFilterEnum(str, Enum):
    READY = "ready"
    NOT_READY = "not_ready"
    STOPPED = "stopped"


@router.get("", response_model=ModelsPublic)
async def get_models(
    session: SessionDep,
    params: ModelListParams = Depends(),
    state: Optional[ModelStateFilterEnum] = Query(
        default=None,
        description="Filter by model state.",
    ),
    search: str = None,
    categories: Optional[List[str]] = Query(None, description="Filter by categories."),
    cluster_id: int = None,
    backend: Optional[str] = Query(None, description="Filter by backend."),
):
    fuzzy_fields = {}
    if search:
        fuzzy_fields = {"name": search}

    fields = {}
    if cluster_id:
        fields["cluster_id"] = cluster_id

    if backend:
        fields["backend"] = backend

    if params.watch:
        return StreamingResponse(
            Model.streaming(
                fields=fields,
                fuzzy_fields=fuzzy_fields,
                filter_func=lambda data: categories_filter(data, categories),
            ),
            media_type="text/event-stream",
        )

    extra_conditions = []
    if categories:
        conditions = build_category_conditions(session, Model, categories)
        extra_conditions.append(or_(*conditions))

    if state is None:
        pass
    elif state == ModelStateFilterEnum.READY:
        extra_conditions.append(Model.ready_replicas > 0)
    elif state == ModelStateFilterEnum.NOT_READY:
        extra_conditions.append(and_(Model.ready_replicas == 0, Model.replicas > 0))
    elif state == ModelStateFilterEnum.STOPPED:
        extra_conditions.append(Model.replicas == 0)

    order_by = params.order_by
    if order_by:
        # When sorting by "source", add additional sorting fields for deterministic ordering
        new_order_by = []
        for field, direction in order_by:
            new_order_by.append((field, direction))
            if field == "source":
                new_order_by.append(("huggingface_repo_id", direction))
                new_order_by.append(("huggingface_filename", direction))
                new_order_by.append(("model_scope_model_id", direction))
                new_order_by.append(("model_scope_file_path", direction))
                new_order_by.append(("local_path", direction))
        order_by = new_order_by

    return await Model.paginated_by_query(
        session=session,
        fuzzy_fields=fuzzy_fields,
        extra_conditions=extra_conditions,
        page=params.page,
        per_page=params.perPage,
        fields=fields,
        order_by=order_by,
    )


@router.get("/{id}", response_model=ModelPublic)
async def get_model(
    session: SessionDep,
    id: int,
):
    return await _get_model(session=session, id=id)


@router.get("/{id}/dashboard")
async def get_model_dashboard(
    session: SessionDep,
    id: int,
    request: Request,
):
    model = await _get_model(session=session, id=id)

    cfg = get_global_config()
    if not cfg.get_grafana_url() or not cfg.grafana_model_dashboard_uid:
        raise InternalServerErrorException(
            message="Grafana dashboard settings are not configured"
        )

    cluster = None
    if model.cluster_id is not None:
        cluster = await Cluster.one_by_id(session, model.cluster_id)

    query_params = {}
    if cluster is not None:
        query_params["var-cluster_name"] = cluster.name
    query_params["var-model_name"] = model.name

    grafana_base = resolve_grafana_base_url(cfg, request)
    slug = "gpustack-model"
    dashboard_url = f"{grafana_base}/d/{cfg.grafana_model_dashboard_uid}/{slug}"
    if query_params:
        dashboard_url = f"{dashboard_url}?{urlencode(query_params)}"

    return RedirectResponse(url=dashboard_url, status_code=302)


async def _get_model(
    session: SessionDep,
    id: int,
):
    model = await Model.one_by_id(session, id)
    if not model:
        raise NotFoundException(message="Model not found")

    return model


@router.get("/{id}/instances", response_model=ModelInstancesPublic)
async def get_model_instances(session: SessionDep, id: int, params: ListParamsDep):
    model = await Model.one_by_id(session, id, options=[selectinload(Model.instances)])
    if not model:
        raise NotFoundException(message="Model not found")

    if params.watch:
        fields = {"model_id": id}
        return StreamingResponse(
            ModelInstance.streaming(fields=fields),
            media_type="text/event-stream",
        )

    instances = model.instances
    count = len(instances)
    total_page = math.ceil(count / params.perPage)
    pagination = Pagination(
        page=params.page,
        perPage=params.perPage,
        total=count,
        totalPage=total_page,
    )

    return ModelInstancesPublic(items=instances, pagination=pagination)


async def validate_model_in(
    session: SessionDep, model_in: Union[ModelCreate, ModelUpdate]
):
    if model_in.gpu_selector is not None and model_in.replicas > 0:
        await validate_gpu_ids(session, model_in)

    if model_in.backend_parameters:
        param_gpu_layers = find_parameter(
            model_in.backend_parameters, ["ngl", "gpu-layers", "n-gpu-layers"]
        )

        if param_gpu_layers:
            int_param_gpu_layers = safe_int(param_gpu_layers, None)
            if (
                not param_gpu_layers.isdigit()
                or int_param_gpu_layers < 0
                or int_param_gpu_layers > 999
            ):
                raise BadRequestException(
                    message="Invalid backend parameter --gpu-layers. Please provide an integer in the range 0-999 (inclusive)."
                )

            if (
                int_param_gpu_layers == 0
                and model_in.gpu_selector is not None
                and len(model_in.gpu_selector.gpu_ids) > 0
            ):
                raise BadRequestException(
                    message="Cannot set --gpu-layers to 0 and manually select GPUs at the same time. Setting --gpu-layers to 0 means running on CPU only."
                )

        param_port = find_parameter(model_in.backend_parameters, ["port"])

        if param_port:
            raise BadRequestException(
                message="Setting the port using --port is not supported."
            )


async def validate_gpu_ids(  # noqa: C901
    session: SessionDep, model_in: Union[ModelCreate, ModelUpdate]
):

    if (
        model_in.gpu_selector
        and model_in.gpu_selector.gpu_ids
        and model_in.gpu_selector.gpus_per_replica
    ):
        if len(model_in.gpu_selector.gpu_ids) < model_in.gpu_selector.gpus_per_replica:
            raise BadRequestException(
                message="The number of selected GPUs must be greater than or equal to gpus_per_replica."
            )

    model_backend = model_in.backend

    if model_backend == BackendEnum.VOX_BOX and (
        len(model_in.gpu_selector.gpu_ids) > 1
        or (
            model_in.gpu_selector.gpus_per_replica is not None
            and model_in.gpu_selector.gpus_per_replica > 1
        )
    ):
        raise BadRequestException(
            message="The vox-box backend is restricted to execution on a single NVIDIA GPU."
        )

    worker_name_set = set()
    for gpu_id in model_in.gpu_selector.gpu_ids:
        is_valid, matched = parse_gpu_id(gpu_id)
        if not is_valid:
            raise BadRequestException(message=f"Invalid GPU ID: {gpu_id}")

        worker_name = matched.get("worker_name")
        gpu_index = safe_int(matched.get("gpu_index"), -1)
        worker_name_set.add(worker_name)

        worker = await WorkerService(session).get_by_name(worker_name)
        if not worker:
            raise BadRequestException(message=f"Worker {worker_name} not found")

        gpu = (
            next(
                (gpu for gpu in worker.status.gpu_devices if gpu.index == gpu_index),
                None,
            )
            if worker.status and worker.status.gpu_devices
            else None
        )
        if gpu:
            validate_gpu(gpu, model_backend=model_backend)

        if model_backend == BackendEnum.VLLM and len(worker_name_set) > 1:
            await validate_distributed_vllm_limit_per_worker(session, model_in, worker)

    if (
        is_custom_backend(model_backend)
        and len(worker_name_set) > 1
        and model_in.replicas == 1
    ):
        raise BadRequestException(
            message="Distributed inference across multiple workers is not supported for custom backends."
        )


def validate_gpu(gpu_device: GPUDeviceStatus, model_backend: str = ""):
    if (
        model_backend == BackendEnum.VOX_BOX
        and gpu_device.vendor != ManufacturerEnum.NVIDIA.value
    ):
        raise BadRequestException(
            "The vox-box backend is supported only on NVIDIA GPUs."
        )

    if (
        model_backend == BackendEnum.ASCEND_MINDIE
        and gpu_device.vendor != ManufacturerEnum.ASCEND.value
    ):
        raise BadRequestException(
            f"Ascend MindIE backend requires Ascend NPUs. Selected {gpu_device.vendor} GPU is not supported."
        )


async def validate_distributed_vllm_limit_per_worker(
    session: AsyncSession, model: Union[ModelCreate, ModelUpdate], worker: Worker
):
    """
    Validate that there is no more than one distributed vLLM instance per worker.
    """
    instances = await ModelInstance.all_by_field(session, "worker_id", worker.id)
    for instance in instances:
        if (
            instance.distributed_servers
            and instance.distributed_servers.subordinate_workers
            and instance.model_name != model.name
        ):
            raise BadRequestException(
                message=f"Each worker can run only one distributed vLLM instance. Worker '{worker.name}' already has '{instance.name}'."
            )


@router.post("", response_model=ModelPublic)
async def create_model(
    session: SessionDep, model_in: ModelCreate, current_user: CurrentUserDep
):
    existing = await Model.one_by_field(session, "name", model_in.name)
    if existing:
        raise AlreadyExistsException(
            message=f"Model '{model_in.name}' already exists. "
            "Please choose a different name or check the existing model."
        )
    should_create_route = (
        model_in.enable_model_route is not None and model_in.enable_model_route
    )
    if should_create_route:
        existing_route = await ModelRoute.one_by_field(session, "name", model_in.name)
        if existing_route:
            raise AlreadyExistsException(
                message=f"Model route '{model_in.name}' already exists. "
                "Please choose a different name or check the existing model route."
            )
    await validate_model_in(session, model_in)
    # Set created_by to current user's ID
    model_in.created_by = current_user.id
    model_in_dict = model_in.model_dump(exclude={"enable_model_route"})

    try:
        await revoke_model_access_cache(session=session)
        # 训练任务（task_type=1）不需要创建 route
        is_training_task = model_in.task_type == 1
        should_create_route = (
            not is_training_task
            and model_in.enable_model_route is not None
            and model_in.enable_model_route
        )
        model: Model = await Model.create(
            session, source=model_in_dict, auto_commit=(not should_create_route)
        )
        if should_create_route:
            model_route = ModelRoute(
                name=model.name,
                description=model.description,
                categories=model.categories,
                generic_proxy=model.generic_proxy,
                created_by_model=True,
                access_policy=model.access_policy,
            )
            model_route: ModelRoute = await ModelRoute.create(
                session, source=model_route, auto_commit=False
            )
            model_route_target = ModelRouteTarget(
                name=f"{model.name}-deployment",
                route_name=model_route.name,
                generic_proxy=model.generic_proxy,
                model_route=model_route,
                model=model,
                weight=100,
                state=TargetStateEnum.UNAVAILABLE,
            )
            await ModelRouteTarget.create(
                session,
                source=model_route_target,
                auto_commit=False,
            )
            await session.commit()
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to create model: {e}")

    # 模型部署成功后，需要将model-catalog对应的is_deployed设置为True
    # model_in的local_path来确定对应的model_catalog_spec
    # 根据model_catalog_spec确定model_catalog
    try:
        # 根据local_path查找对应的model_catalog_spec
        from gpustack.schemas.model_catalog import ModelCatalogSpec

        spec_result = await session.exec(
            select(ModelCatalogSpec).where(
                ModelCatalogSpec.local_path == model_in.local_path,
                ModelCatalogSpec.deleted_at.is_(None),
            )
        )
        spec = spec_result.first()

        # 如果找到spec，获取对应的model_catalog并设置is_deployed为True
        if spec:
            model_catalog = await ModelCatalog.one_by_id(session, spec.model_catalog_id)
            if model_catalog:
                model_catalog.is_deployed = True
                await session.commit()
    except Exception as e:
        # 记录错误但不影响模型创建
        import logging

        logging.error(f"Failed to update model catalog is_deployed: {e}")

    return model


@router.put("/{id}", response_model=ModelPublic)
async def update_model(session: SessionDep, id: int, model_in: ModelUpdate):
    model = await Model.one_by_id(session, id)
    if not model:
        raise NotFoundException(message="Model not found")

    await validate_model_in(session, model_in)

    if model_in.backend != BackendEnum.CUSTOM.value and (
        model.run_command or model.image_name
    ):
        patch = model_in.model_dump(exclude_unset=True)
        patch["run_command"] = None
        patch["image_name"] = None
        model_in = patch

    try:
        await ModelService(session).update(model, model_in)
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to update model: {e}")

    return model


@router.delete("/{id}")
async def delete_model(session: SessionDep, id: int):
    model = await Model.one_by_id(
        session,
        id,
        options=[
            selectinload(Model.instances),
            selectinload(Model.model_route_targets),
        ],
    )
    if not model:
        raise NotFoundException(message="Model not found")

    try:
        await ModelService(session).delete(model)
        # 根据local_path查找对应的model_catalog_spec
        from gpustack.schemas.model_catalog import ModelCatalogSpec

        spec_result = await session.exec(
            select(ModelCatalogSpec).where(
                ModelCatalogSpec.local_path == model.local_path,
                ModelCatalogSpec.deleted_at.is_(None),
            )
        )
        spec = spec_result.first()

        # 如果找到spec，获取对应的model_catalog并设置is_deployed为False
        if spec:
            model_catalog = await ModelCatalog.one_by_id(session, spec.model_catalog_id)
            # 增加一个判断，就是没有其他的部署也用到此model_catalog
            # 查看当前部署的所有models中是否还有引用此model_catalog的
            if model_catalog:
                # 查询是否有其他模型使用此model_catalog
                from gpustack.schemas.model_catalog import ModelCatalogSpec

                other_models_result = await session.exec(
                    select(Model)
                    .join(
                        ModelCatalogSpec,
                        Model.local_path == ModelCatalogSpec.local_path,
                    )
                    .where(
                        ModelCatalogSpec.model_catalog_id == model_catalog.id,
                        Model.id != model.id,  # 排除当前正在删除的模型
                        Model.deleted_at.is_(None),
                    )
                )
                other_models = other_models_result.all()

                # 如果没有其他模型使用此model_catalog，则将is_deployed设置为False
                if not other_models:
                    model_catalog.is_deployed = False
                    await session.commit()
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to delete model: {e}")


async def revoke_model_access_cache(
    session: AsyncSession,
    model: Optional[Model] = None,
    extra_user_ids: Optional[set[int]] = None,
):
    user_ids = set()
    if model is None:
        users = await User.all(session)
        user_ids = {user.id for user in users}
    else:
        user_ids = {user.id for user in model.users}
    if extra_user_ids:
        user_ids.update(extra_user_ids)
    await delete_accessible_model_cache(session, *user_ids)


@router.get("/by-catalog/{catalog_id}", response_model=ModelsPublicWithInstances)
async def get_models_by_catalog(
    session: SessionDep,
    catalog_id: int,
):
    """
    根据 model_catalog 的 id 获取当前已经部署的模型实例

    逻辑：
    1. 找到对应 model_catalog 的 spec 对应的 local_path
    2. 去 model_instances 中找到对应的记录
    3. 找到对应的 model
    4. 返回多个 model 下带 model_instance 的记录
    """
    # 查询模型目录及其规格
    model_catalog = await session.get(
        ModelCatalog, catalog_id, options=[selectinload(ModelCatalog.specs)]
    )
    if not model_catalog:
        raise NotFoundException(
            message=f"Model catalog with id '{catalog_id}' not found"
        )

    # 收集所有规格的 local_path
    local_paths = []
    for spec in model_catalog.specs:
        if spec.local_path:
            local_paths.append(spec.local_path)

    if not local_paths:
        # 没有找到 local_path，返回空结果
        return ModelsPublicWithInstances(
            items=[], pagination={"page": 1, "perPage": 10, "total": 0, "totalPage": 0}
        )

    # 查询包含这些 local_path 的模型
    models_result = await session.exec(
        select(Model)
        .where(Model.local_path.in_(local_paths))
        .options(selectinload(Model.instances))
    )
    models = models_result.all()

    # 构建响应
    items = []
    for model in models:
        # 确保模型实例被正确加载
        if not hasattr(model, 'instances'):
            # 如果没有加载实例，手动查询
            instances_result = await session.exec(
                select(ModelInstance).where(ModelInstance.model_id == model.id)
            )
            model.instances = instances_result.all()

        # 构建包含实例的模型公共信息
        model_data = model.model_dump()
        model_data['instances'] = model.instances
        model_public = ModelPublicWithInstances(**model_data)
        items.append(model_public)

    return ModelsPublicWithInstances(
        items=items,
        pagination={
            "page": 1,
            "perPage": len(items),
            "total": len(items),
            "totalPage": 1,
        },
    )
