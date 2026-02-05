from typing import Optional
import aiohttp
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, StreamingResponse, RedirectResponse
from urllib.parse import urlencode
from sqlalchemy.orm import selectinload

from gpustack.api.responses import StreamingResponseWithStatusCode
from gpustack import envs
from gpustack.server.services import ModelInstanceService, ModelService
from gpustack.utils.network import use_proxy_env_for_url
from gpustack.worker.logs import LogOptionsDep
from gpustack.api.exceptions import (
    InternalServerErrorException,
    NotFoundException,
)
from gpustack.schemas.workers import Worker
from gpustack.schemas.clusters import Cluster
from gpustack.server.deps import ListParamsDep, SessionDep
from gpustack.schemas.models import (
    Model,
    ModelInstance,
    ModelInstanceCreate,
    ModelInstancePublic,
    ModelInstanceUpdate,
    ModelInstancesPublic,
    ModelInstanceStateEnum,
    ModelUpdate,
    TrainHistory,
    TrainInstancesHistory,
)
from gpustack.schemas.model_files import ModelFileStateEnum
from gpustack.config.config import get_global_config
from gpustack.utils.grafana import resolve_grafana_base_url

router = APIRouter()


@router.get("", response_model=ModelInstancesPublic)
async def get_model_instances(
    session: SessionDep,
    params: ListParamsDep,
    id: Optional[int] = None,
    model_id: Optional[int] = None,
    worker_id: Optional[int] = None,
    state: Optional[str] = None,
):
    fields = {}
    if id:
        fields["id"] = id

    if model_id:
        fields["model_id"] = model_id

    if worker_id:
        fields["worker_id"] = worker_id

    if state:
        fields["state"] = state

    if params.watch:
        return StreamingResponse(
            ModelInstance.streaming(fields=fields),
            media_type="text/event-stream",
        )

    return await ModelInstance.paginated_by_query(
        session=session,
        fields=fields,
        page=params.page,
        per_page=params.perPage,
    )


@router.get("/{id}", response_model=ModelInstancePublic)
async def get_model_instance(
    session: SessionDep,
    id: int,
):
    model_instance = await ModelInstance.one_by_id(session, id)
    if not model_instance:
        raise NotFoundException(message="Model instance not found")
    return model_instance


@router.get("/{id}/dashboard")
async def get_model_instance_dashboard(
    session: SessionDep,
    id: int,
    request: Request,
):
    model_instance = await ModelInstance.one_by_id(session, id)
    if not model_instance:
        raise NotFoundException(message="Model instance not found")

    cfg = get_global_config()
    if not cfg.get_grafana_url() or not cfg.grafana_model_dashboard_uid:
        raise InternalServerErrorException(
            message="Grafana dashboard settings are not configured"
        )

    cluster = None
    if model_instance.cluster_id is not None:
        cluster = await Cluster.one_by_id(session, model_instance.cluster_id)

    query_params = {}
    if cluster is not None:
        query_params["var-cluster_name"] = cluster.name
    query_params["var-model_name"] = model_instance.model_name
    query_params["var-model_instance_name"] = model_instance.name

    grafana_base = resolve_grafana_base_url(cfg, request)
    slug = "gpustack-model"
    dashboard_url = f"{grafana_base}/d/{cfg.grafana_model_dashboard_uid}/{slug}"
    if query_params:
        dashboard_url = f"{dashboard_url}?{urlencode(query_params)}"

    return RedirectResponse(url=dashboard_url, status_code=302)


async def fetch_model_instance(session, id):
    model_instance = await ModelInstance.one_by_id(
        session, id, options=[selectinload(ModelInstance.model_files)]
    )
    if not model_instance:
        raise NotFoundException(message="Model instance not found")
    if not model_instance.worker_id:
        raise NotFoundException(message="Model instance not assigned to a worker")
    return model_instance


async def fetch_worker(session, worker_id):
    worker = await Worker.one_by_id(session, worker_id)
    if not worker:
        raise NotFoundException(message="Model instance's worker not found")
    return worker


@router.get("/{id}/logs")
async def get_serving_logs(  # noqa: C901
    request: Request, session: SessionDep, id: int, log_options: LogOptionsDep
):
    model_instance = await fetch_model_instance(session, id)
    worker = await fetch_worker(session, model_instance.worker_id)

    model_instance_log_url = (
        f"http://{worker.advertise_address}:{worker.port}/serveLogs"
        f"/{model_instance.id}?{log_options.url_encode()}"
        f"&model_instance_name={model_instance.name}"
    )
    if (
        model_instance.state != ModelInstanceStateEnum.RUNNING
        and model_instance.model_files
        and model_instance.model_files[0].state != ModelFileStateEnum.READY
    ):
        # Get model file ID for injected download logs if instance is downloading
        model_instance_log_url += f"&model_file_id={model_instance.model_files[0].id}"

    timeout = aiohttp.ClientTimeout(total=envs.PROXY_TIMEOUT, sock_connect=5)

    use_proxy_env = use_proxy_env_for_url(model_instance_log_url)
    client: aiohttp.ClientSession = (
        request.app.state.http_client
        if use_proxy_env
        else request.app.state.http_client_no_proxy
    )

    if log_options.follow:

        async def proxy_stream():
            try:
                async with client.get(model_instance_log_url, timeout=timeout) as resp:
                    if resp.status != 200:
                        body = await resp.read()
                        yield body, resp.headers, resp.status
                        return

                    async for chunk in resp.content.iter_any():
                        yield chunk, resp.headers, resp.status
            except TimeoutError:
                yield "\x1b[999;1H" + f"Log stream timed out ({timeout.total} seconds). Please reopen the log page.\n", {}, status.HTTP_500_INTERNAL_SERVER_ERROR
            except Exception as e:
                yield "\x1b[999;1H" + f"Error fetching serving logs: {str(e)}\n", {}, status.HTTP_500_INTERNAL_SERVER_ERROR

        return StreamingResponseWithStatusCode(
            proxy_stream(),
            media_type="application/octet-stream",
        )
    else:
        try:
            async with client.get(model_instance_log_url, timeout=timeout) as resp:
                if resp.status != 200:
                    raise HTTPException(
                        status_code=resp.status,
                        detail="Error fetching serving logs",
                    )
                content = await resp.text()
            return PlainTextResponse(content=content, status_code=resp.status)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error fetching serving logs: {str(e)}\n"
            )


@router.post("", response_model=ModelInstancePublic)
async def create_model_instance(
    session: SessionDep, model_instance_in: ModelInstanceCreate
):
    try:
        model_instance = await ModelInstance.create(session, model_instance_in)
    except Exception as e:
        raise InternalServerErrorException(
            message=f"Failed to create model instance: {e}"
        )
    return model_instance


@router.put("/{id}", response_model=ModelInstancePublic)
async def update_model_instance(
    session: SessionDep, id: int, model_instance_in: ModelInstanceUpdate
):
    model_instance = await ModelInstance.one_by_id(session, id, for_update=True)
    if not model_instance:
        raise NotFoundException(message="Model instance not found")

    try:
        # 如果是针对complete，那说明是训练任务结束了，执行对应的停止删除操作
        if model_instance_in.state == ModelInstanceStateEnum.COMPLETED:
            # 训练任务完成，需要停止并删除模型实例
            # 直接执行models的对应的接口即可，同时将训练的历史任务记录
            # 先根据model_instance的model_id查询model
            model = await Model.one_by_id(session, model_instance.model_id)
            if not model:
                raise NotFoundException(message="Model not found")

            # 创建训练历史记录
            # 复制model的所有字段到TrainHistory
            model_dict = model.model_dump()
            # 移除id字段，让数据库自动生成
            model_dict.pop('id', None)
            # 创建TrainHistory记录
            train_history = TrainHistory(**model_dict)
            train_history = await TrainHistory.create(
                session, source=train_history, auto_commit=False
            )

            # 复制model_instance的所有字段到TrainInstancesHistory
            model_instance_dict = model_instance.model_dump()
            # 移除id字段，让数据库自动生成
            model_instance_dict.pop('id', None)
            # 设置train_history_id关联
            model_instance_dict['train_history_id'] = train_history.id
            # 创建TrainInstancesHistory记录
            train_instance_history = TrainInstancesHistory(**model_instance_dict)
            await TrainInstancesHistory.create(
                session, source=train_instance_history, auto_commit=True
            )

            # 将模型的replicas设置为0
            # 从现有的model对象创建ModelUpdate对象，包含所有必需的字段
            model_in = ModelUpdate(**model.model_dump())
            # 只修改replicas字段
            model_in.replicas = 0
            await ModelService(session).update(model, model_in)
            # 再删除模型实例
            model = await Model.one_by_id(
                session,
                model_instance.model_id,
                options=[
                    selectinload(Model.instances),
                    selectinload(Model.model_route_targets),
                ],
            )
            if not model:
                raise NotFoundException(message="Model not found")
            try:
                await ModelService(session).delete(model)
            except Exception as e:
                raise InternalServerErrorException(
                    message=f"Failed to delete model: {e}"
                )
        else:
            await ModelInstanceService(session).update(
                model_instance, model_instance_in
            )
    except Exception as e:
        raise InternalServerErrorException(
            message=f"Failed to update model instance: {e}"
        )
    return model_instance


@router.delete("/{id}")
async def delete_model_instance(session: SessionDep, id: int):
    model_instance = await ModelInstance.one_by_id(session, id, for_update=True)
    if not model_instance:
        raise NotFoundException(message="Model instance not found")

    try:
        await ModelInstanceService(session).delete(model_instance)
    except Exception as e:
        raise InternalServerErrorException(
            message=f"Failed to delete model instance: {e}"
        )
