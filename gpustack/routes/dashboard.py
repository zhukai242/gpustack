from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from fastapi import APIRouter, Query
from sqlmodel import desc, distinct, select, func, col
from sqlmodel.ext.asyncio.session import AsyncSession

from gpustack.schemas.common import ItemList
from gpustack.schemas.dashboard import (
    CurrentSystemLoad,
    HistorySystemLoad,
    ModelSummary,
    ModelUsageStats,
    ModelUsageSummary,
    ModelUsageUserSummary,
    ResourceClaim,
    ResourceCounts,
    SystemLoadSummary,
    SystemSummary,
    TimeSeriesData,
    WorkerLoadSummary,
    GPULoadSummary,
    CurrentWorkerLoad,
    HistoryWorkerLoad,
    CurrentGPULoad,
    HistoryGPULoad,
)
from gpustack.schemas.model_usage import ModelUsage
from gpustack.schemas.models import Model, ModelInstance
from gpustack.schemas.system_load import SystemLoad
from gpustack.schemas.users import User
from gpustack.server.deps import SessionDep
from gpustack.schemas import Worker, Cluster
from gpustack.schemas.load import WorkerLoad, GPULoad
from gpustack.schemas.model_provider import ModelProvider
from gpustack.server.system_load import compute_system_load

router = APIRouter()


@router.get("")
async def dashboard(
    session: SessionDep,
    cluster_id: Optional[int] = None,
):
    resoruce_counts = await get_resource_counts(session, cluster_id)
    system_load = await get_system_load(session, cluster_id)
    model_usage = await get_model_usage_summary(session, cluster_id)
    active_models = await get_active_models(session, cluster_id)
    summary = SystemSummary(
        cluster_id=cluster_id,
        resource_counts=resoruce_counts,
        system_load=system_load,
        model_usage=model_usage,
        active_models=active_models,
    )

    return summary


async def get_resource_counts(
    session: AsyncSession, cluster_id: Optional[int] = None
) -> ResourceCounts:
    fields = {}
    cluster_count = None
    if cluster_id is not None:
        fields['cluster_id'] = cluster_id
    else:
        clusters = await Cluster.all_by_field(session, field="deleted_at", value=None)
        cluster_count = len(clusters)
    workers = await Worker.all_by_fields(
        session,
        fields=fields,
    )
    worker_count = len(workers)
    gpu_count = 0
    for worker in workers:
        gpu_count += len(worker.status.gpu_devices or [])
    models = await Model.all_by_fields(session, fields=fields)
    model_count = len(models)
    model_instances = await ModelInstance.all_by_fields(session, fields=fields)
    model_instance_count = len(model_instances)
    return ResourceCounts(
        cluster_count=cluster_count,
        worker_count=worker_count,
        gpu_count=gpu_count,
        model_count=model_count,
        model_instance_count=model_instance_count,
    )


async def get_system_load(
    session: AsyncSession, cluster_id: Optional[int] = None
) -> SystemLoadSummary:
    fields = {}
    if cluster_id is not None:
        fields['cluster_id'] = cluster_id
    workers = await Worker.all_by_fields(session, fields=fields)
    current_system_loads = compute_system_load(workers)
    current_system_load = next(
        (load for load in current_system_loads if load.cluster_id == cluster_id),
        SystemLoad(
            cluster_id=cluster_id,
            cpu=0,
            ram=0,
            gpu=0,
            vram=0,
        ),
    )

    now = datetime.now(timezone.utc)

    one_hour_ago = int((now - timedelta(hours=1)).timestamp())

    statement = select(SystemLoad)
    statement = statement.where(SystemLoad.cluster_id == cluster_id)
    statement = statement.where(SystemLoad.timestamp >= one_hour_ago)

    system_loads = (await session.exec(statement)).all()

    cpu = []
    ram = []
    gpu = []
    vram = []
    for system_load in system_loads:
        cpu.append(
            TimeSeriesData(
                timestamp=system_load.timestamp,
                value=system_load.cpu,
            )
        )
        ram.append(
            TimeSeriesData(
                timestamp=system_load.timestamp,
                value=system_load.ram,
            )
        )
        gpu.append(
            TimeSeriesData(
                timestamp=system_load.timestamp,
                value=system_load.gpu,
            )
        )
        vram.append(
            TimeSeriesData(
                timestamp=system_load.timestamp,
                value=system_load.vram,
            )
        )
    cpu.sort(key=lambda x: x.timestamp, reverse=False)
    ram.sort(key=lambda x: x.timestamp, reverse=False)
    gpu.sort(key=lambda x: x.timestamp, reverse=False)
    vram.sort(key=lambda x: x.timestamp, reverse=False)
    return SystemLoadSummary(
        current=CurrentSystemLoad(
            cpu=current_system_load.cpu,
            ram=current_system_load.ram,
            gpu=current_system_load.gpu,
            vram=current_system_load.vram,
        ),
        history=HistorySystemLoad(
            cpu=cpu,
            ram=ram,
            gpu=gpu,
            vram=vram,
        ),
    )


async def get_model_usage_stats(
    session: AsyncSession,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    model_ids: Optional[List[int]] = None,
    user_ids: Optional[List[int]] = None,
    cluster_id: Optional[int] = None,
) -> ModelUsageStats:
    if start_date is None or end_date is None:
        end_date = date.today()
        start_date = end_date - timedelta(days=31)
    if model_ids is None and cluster_id is not None:
        models = await Model.all_by_fields(session, fields={"cluster_id": cluster_id})
        model_ids = [model.id for model in models]
    statement = (
        select(
            ModelUsage.date,
            func.sum(ModelUsage.prompt_token_count).label('total_prompt_tokens'),
            func.sum(ModelUsage.completion_token_count).label(
                'total_completion_tokens'
            ),
            func.sum(ModelUsage.request_count).label('total_requests'),
        )
        .where(ModelUsage.date >= start_date)
        .where(ModelUsage.date <= end_date)
        .group_by(ModelUsage.date)
        .order_by(ModelUsage.date)
    )

    if model_ids is not None:
        statement = statement.where(col(ModelUsage.model_id).in_(model_ids))

    if user_ids is not None:
        statement = statement.where(col(ModelUsage.user_id).in_(user_ids))

    results = (await session.exec(statement)).all()

    prompt_token_history = []
    completion_token_history = []
    api_request_history = []
    for result in results:
        prompt_token_history.append(
            TimeSeriesData(
                timestamp=int(
                    datetime.combine(result.date, datetime.min.time()).timestamp()
                ),
                value=result.total_prompt_tokens,
            )
        )
        completion_token_history.append(
            TimeSeriesData(
                timestamp=int(
                    datetime.combine(result.date, datetime.min.time()).timestamp()
                ),
                value=result.total_completion_tokens,
            )
        )
        api_request_history.append(
            TimeSeriesData(
                timestamp=int(
                    datetime.combine(result.date, datetime.min.time()).timestamp()
                ),
                value=result.total_requests,
            )
        )

    return ModelUsageStats(
        api_request_history=api_request_history,
        prompt_token_history=prompt_token_history,
        completion_token_history=completion_token_history,
    )


async def get_model_usage_summary(
    session: AsyncSession, cluster_id: Optional[int] = None
) -> ModelUsageSummary:
    model_usage_stats = await get_model_usage_stats(session, cluster_id=cluster_id)
    # get top users
    today = date.today()
    one_month_ago = today - timedelta(days=31)

    statement = (
        select(
            ModelUsage.user_id,
            User.username,
            func.sum(ModelUsage.prompt_token_count).label('total_prompt_tokens'),
            func.sum(ModelUsage.completion_token_count).label(
                'total_completion_tokens'
            ),
        )
        .join(User, ModelUsage.user_id == User.id)
        .where(ModelUsage.date >= one_month_ago)
        .group_by(ModelUsage.user_id, User.username)
        .order_by(
            func.sum(
                ModelUsage.prompt_token_count + ModelUsage.completion_token_count
            ).desc()
        )
        .limit(10)
    )

    results = (await session.exec(statement)).all()
    top_users = []
    for result in results:
        top_users.append(
            ModelUsageUserSummary(
                user_id=result.user_id,
                username=result.username,
                prompt_token_count=result.total_prompt_tokens,
                completion_token_count=result.total_completion_tokens,
            )
        )

    return ModelUsageSummary(
        api_request_history=model_usage_stats.api_request_history,
        prompt_token_history=model_usage_stats.prompt_token_history,
        completion_token_history=model_usage_stats.completion_token_history,
        top_users=top_users,
    )


async def _get_maas_active_models(session: AsyncSession) -> List[ModelSummary]:
    all_providers = await ModelProvider.all_by_field(
        session, field="deleted_at", value=None
    )
    if not all_providers:
        return []

    provider_ids = [p.id for p in all_providers]
    total_tokens = func.sum(
        ModelUsage.prompt_token_count + ModelUsage.completion_token_count
    )
    # Aggregate model usage in the database for efficiency
    statement = (
        select(
            ModelUsage.provider_id,
            ModelUsage.model_name,
            total_tokens.label("total_token_count"),
        )
        .where(col(ModelUsage.provider_id).in_(provider_ids))
        .group_by(ModelUsage.provider_id, ModelUsage.model_name)
        .order_by(func.coalesce(total_tokens, 0).desc())
        .limit(10)
    )
    top_model_usages = (await session.exec(statement)).all()

    models_by_provider_and_name = {
        (p.id, m.name): m for p in all_providers for m in (p.models or [])
    }

    provider_id_to_name = {p.id: p.name for p in all_providers}

    model_summaries = []
    for usage in top_model_usages:
        model = models_by_provider_and_name.get((usage.provider_id, usage.model_name))

        model_summaries.append(
            ModelSummary(
                provider_id=usage.provider_id,
                provider_name=provider_id_to_name.get(
                    usage.provider_id, "Unknown Provider"
                ),
                name=usage.model_name,
                instance_count=0,
                token_count=int(usage.total_token_count or 0),
                categories=([model.category] if model and model.category else None),
            )
        )

    return model_summaries


async def _get_gpustack_active_models(
    session: AsyncSession, cluster_id: Optional[int] = None
) -> List[ModelSummary]:
    statement = active_model_statement(cluster_id=cluster_id)

    results = (await session.exec(statement)).all()

    top_model_ids = [result.id for result in results]
    extra_conditions = [
        col(ModelInstance.model_id).in_(top_model_ids),
    ]
    model_instances: List[ModelInstance] = await ModelInstance.all_by_fields(
        session, fields={}, extra_conditions=extra_conditions
    )
    model_instances_by_id: Dict[int, List[ModelInstance]] = {}
    for model_instance in model_instances:
        if model_instance.model_id not in model_instances_by_id:
            model_instances_by_id[model_instance.model_id] = []
        model_instances_by_id[model_instance.model_id].append(model_instance)

    model_summary = []
    for result in results:
        # We need to summarize the resource claims for all model instances
        # including distributed servers. It's complicated to do this in a SQL
        # statement, so we do it in Python.
        resource_claim = ResourceClaim(
            ram=0,
            vram=0,
        )
        if result.id in model_instances_by_id:
            for model_instance in model_instances_by_id[result.id]:
                aggregate_resource_claim(resource_claim, model_instance)

        model_summary.append(
            ModelSummary(
                id=result.id,
                name=result.name,
                categories=result.categories,
                resource_claim=resource_claim,
                instance_count=result.instance_count,
                token_count=(
                    result.total_token_count
                    if result.total_token_count is not None
                    else 0
                ),
            )
        )

    return model_summary


async def get_active_models(
    session: AsyncSession, cluster_id: Optional[int] = None
) -> List[ModelSummary]:
    summary = await _get_gpustack_active_models(session, cluster_id)
    if cluster_id is None:
        maas_active_models = await _get_maas_active_models(session)
        summary.extend(maas_active_models)
    summary.sort(key=lambda x: x.token_count, reverse=True)
    summary = summary[:10]
    return summary


def aggregate_resource_claim(
    resource_claim: ResourceClaim,
    model_instance: ModelInstance,
):
    if model_instance.computed_resource_claim is not None:
        resource_claim.ram += model_instance.computed_resource_claim.ram or 0
        for vram in (model_instance.computed_resource_claim.vram or {}).values():
            resource_claim.vram += vram

    if (
        model_instance.distributed_servers
        and model_instance.distributed_servers.subordinate_workers
    ):
        for subworker in model_instance.distributed_servers.subordinate_workers:
            if subworker.computed_resource_claim is not None:
                resource_claim.ram += subworker.computed_resource_claim.ram or 0
                for vram in (subworker.computed_resource_claim.vram or {}).values():
                    resource_claim.vram += vram


def active_model_statement(cluster_id: Optional[int]) -> select:
    usage_sum_query = (
        select(
            Model.id.label('model_id'),
            func.sum(
                ModelUsage.prompt_token_count + ModelUsage.completion_token_count
            ).label('total_token_count'),
        )
        .outerjoin(ModelUsage, Model.id == ModelUsage.model_id)
        .group_by(Model.id)
    ).alias('usage_sum')

    statement = select(
        Model.id,
        Model.name,
        Model.categories,
        func.count(distinct(ModelInstance.id)).label('instance_count'),
        usage_sum_query.c.total_token_count,
    )
    if cluster_id is not None:
        statement = statement.where(Model.cluster_id == cluster_id)

    statement = (
        statement.join(ModelInstance, Model.id == ModelInstance.model_id)
        .outerjoin(usage_sum_query, Model.id == usage_sum_query.c.model_id)
        .group_by(
            Model.id,
            usage_sum_query.c.total_token_count,
        )
        .order_by(func.coalesce(usage_sum_query.c.total_token_count, 0).desc())
        .limit(10)
    )

    return statement


async def get_model_usages(
    session: AsyncSession,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    model_ids: Optional[List[int]] = None,
    user_ids: Optional[List[int]] = None,
) -> List[ModelUsage]:
    if start_date is None or end_date is None:
        end_date = date.today()
        start_date = end_date - timedelta(days=31)

    statement = (
        select(ModelUsage)
        .where(ModelUsage.date >= start_date)
        .where(ModelUsage.date <= end_date)
    )

    if model_ids is not None:
        statement = statement.where(col(ModelUsage.model_id).in_(model_ids))

    if user_ids is not None:
        statement = statement.where(col(ModelUsage.user_id).in_(user_ids))

    statement = statement.order_by(
        desc(ModelUsage.date),
        ModelUsage.user_id,
        ModelUsage.completion_token_count,
    )

    return (await session.exec(statement)).all()


@router.get("/usage")
async def usage(
    session: SessionDep,
    start_date: Optional[date] = Query(
        None,
        description="Start date for the usage data (YYYY-MM-DD). Defaults to 31 days ago.",
    ),
    end_date: Optional[date] = Query(
        None, description="End date for the usage data (YYYY-MM-DD). Defaults to today."
    ),
    model_ids: Optional[List[int]] = Query(
        None,
        description="Filter by model IDs. Defaults to all models.",
    ),
    user_ids: Optional[List[int]] = Query(
        None, description="Filter by user IDs. Defaults to all users."
    ),
):
    """
    Get model usage records.
    This endpoint returns detailed model usage records within a specified date range.
    """
    items = await get_model_usages(
        session,
        start_date=start_date,
        end_date=end_date,
        model_ids=model_ids,
        user_ids=user_ids,
    )
    return ItemList[ModelUsage](items=items)


@router.get("/usage/stats")
async def usage_stats(
    session: SessionDep,
    start_date: Optional[date] = Query(
        None,
        description="Start date for the usage data (YYYY-MM-DD). Defaults to 31 days ago.",
    ),
    end_date: Optional[date] = Query(
        None, description="End date for the usage data (YYYY-MM-DD). Defaults to today."
    ),
    model_ids: Optional[List[int]] = Query(
        None,
        description="Filter by model IDs. Defaults to all models.",
    ),
    user_ids: Optional[List[int]] = Query(
        None, description="Filter by user IDs. Defaults to all users."
    ),
):
    """
    Get model usage statistics.
    This endpoint returns aggregated statistics for model usage,
    including token counts and request counts. It can filter by date
    range, model IDs, and user IDs.
    """
    return await get_model_usage_stats(
        session,
        start_date=start_date,
        end_date=end_date,
        model_ids=model_ids,
        user_ids=user_ids,
    )


@router.get("/worker-load/{worker_id}")
async def worker_load(
    session: SessionDep,
    worker_id: int,
):
    """
    Get worker usage trends.
    This endpoint returns the current and historical usage data for a specific worker.
    """
    # Get current worker status
    worker = await Worker.one_by_id(session, worker_id)
    if not worker:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Worker not found")

    # Calculate current load from worker status
    current_cpu = (
        worker.status.cpu.utilization_rate if worker.status and worker.status.cpu else 0
    )
    current_ram = (
        worker.status.memory.utilization_rate
        if worker.status and worker.status.memory
        else 0
    )

    # Calculate average GPU/VRAM for this worker
    current_gpu = 0
    current_vram = 0
    if worker.status and worker.status.gpu_devices:
        total_gpu_util = 0.0
        total_vram_util = 0.0
        valid_gpu_count = 0
        valid_vram_count = 0

        for gpu in worker.status.gpu_devices:
            if gpu.core and gpu.core.utilization_rate is not None:
                total_gpu_util += gpu.core.utilization_rate
                valid_gpu_count += 1
            if gpu.memory and gpu.memory.utilization_rate is not None:
                total_vram_util += gpu.memory.utilization_rate
                valid_vram_count += 1

        if valid_gpu_count > 0:
            current_gpu = total_gpu_util / valid_gpu_count
        if valid_vram_count > 0:
            current_vram = total_vram_util / valid_vram_count

    # Get historical data from worker_loads table
    now = datetime.now(timezone.utc)
    one_hour_ago = int((now - timedelta(hours=1)).timestamp())

    statement = select(WorkerLoad)
    statement = statement.where(WorkerLoad.worker_id == worker_id)
    statement = statement.where(WorkerLoad.timestamp >= one_hour_ago)
    statement = statement.order_by(WorkerLoad.timestamp.asc())

    worker_loads = (await session.exec(statement)).all()

    # Prepare time series data
    cpu_history = []
    ram_history = []
    gpu_history = []
    vram_history = []

    for load in worker_loads:
        cpu_history.append(
            TimeSeriesData(timestamp=load.timestamp, value=load.cpu or 0)
        )
        ram_history.append(
            TimeSeriesData(timestamp=load.timestamp, value=load.ram or 0)
        )
        gpu_history.append(
            TimeSeriesData(timestamp=load.timestamp, value=load.gpu or 0)
        )
        vram_history.append(
            TimeSeriesData(timestamp=load.timestamp, value=load.vram or 0)
        )

    # Create response
    return WorkerLoadSummary(
        current=CurrentWorkerLoad(
            cpu=current_cpu,
            ram=current_ram,
            gpu=current_gpu,
            vram=current_vram,
        ),
        history=HistoryWorkerLoad(
            cpu=cpu_history,
            ram=ram_history,
            gpu=gpu_history,
            vram=vram_history,
        ),
    )


@router.get("/gpu-load/{gpu_id}")
async def gpu_load(
    session: SessionDep,
    gpu_id: str,
):
    """
    Get GPU usage trends.
    This endpoint returns the current and historical usage data for a specific GPU.
    """
    # Get current GPU status from worker
    # First, we need to find the worker and GPU index from gpu_id
    # gpu_id format: worker_name:gpu_type:gpu_index
    parts = gpu_id.split(":")
    if len(parts) < 3:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid GPU ID format")

    worker_name = parts[0]
    gpu_index = int(parts[2])

    # Find the worker
    workers = await Worker.all_by_field(session, field="name", value=worker_name)
    if not workers:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Worker not found")

    worker = workers[0]
    current_gpu_util = 0
    current_vram_util = 0

    # Find the GPU device
    if (
        worker.status
        and worker.status.gpu_devices
        and len(worker.status.gpu_devices) > gpu_index
    ):
        gpu = worker.status.gpu_devices[gpu_index]
        current_gpu_util = gpu.core.utilization_rate if gpu.core else 0
        current_vram_util = gpu.memory.utilization_rate if gpu.memory else 0

    # Get historical data from gpu_loads table
    now = datetime.now(timezone.utc)
    one_hour_ago = int((now - timedelta(hours=1)).timestamp())

    statement = select(GPULoad)
    statement = statement.where(GPULoad.gpu_id == gpu_id)
    statement = statement.where(GPULoad.timestamp >= one_hour_ago)
    statement = statement.order_by(GPULoad.timestamp.asc())

    gpu_loads = (await session.exec(statement)).all()

    # Prepare time series data
    gpu_history = []
    vram_history = []

    for load in gpu_loads:
        gpu_history.append(
            TimeSeriesData(timestamp=load.timestamp, value=load.gpu_utilization or 0)
        )
        vram_history.append(
            TimeSeriesData(timestamp=load.timestamp, value=load.vram_utilization or 0)
        )

    # Create response
    return GPULoadSummary(
        current=CurrentGPULoad(
            gpu=current_gpu_util,
            vram=current_vram_util,
        ),
        history=HistoryGPULoad(
            gpu=gpu_history,
            vram=vram_history,
        ),
    )


async def _get_basic_stats(workers):
    """
    Calculate basic GPU and worker statistics from worker status.

    Args:
        workers: List of Worker objects

    Returns:
        Tuple containing gpu_total, total_memory, gpu_temperatures, abnormal_devices,
        total_gpu_util, gpu_count_for_util
    """
    gpu_total = 0
    total_memory = 0
    gpu_temperatures = []
    abnormal_devices = 0
    total_gpu_util = 0.0
    gpu_count_for_util = 0

    for worker in workers:
        # Get total memory from worker
        if worker.status and worker.status.memory:
            total_memory += worker.status.memory.total

        # Process GPU devices
        if worker.status and worker.status.gpu_devices:
            for gpu in worker.status.gpu_devices:
                gpu_total += 1

                # Check for abnormal devices
                if (
                    (
                        gpu.core
                        and gpu.core.utilization_rate is not None
                        and gpu.core.utilization_rate > 95
                    )
                    or (
                        gpu.memory
                        and gpu.memory.utilization_rate is not None
                        and gpu.memory.utilization_rate > 95
                    )
                    or (gpu.temperature and gpu.temperature > 85)
                ):
                    abnormal_devices += 1

                # Collect GPU utilization for overall utilization
                if gpu.core and gpu.core.utilization_rate is not None:
                    total_gpu_util += gpu.core.utilization_rate
                    gpu_count_for_util += 1

                # Collect GPU temperatures
                if gpu.temperature is not None:
                    gpu_temperatures.append(gpu.temperature)

    return (
        gpu_total,
        total_memory,
        gpu_temperatures,
        abnormal_devices,
        total_gpu_util,
        gpu_count_for_util,
    )


async def _get_current_utilization(workers, total_gpu_util, gpu_count_for_util):
    """
    Calculate current GPU and VRAM utilization from worker status.

    Args:
        workers: List of Worker objects
        total_gpu_util: Total GPU utilization from all workers
        gpu_count_for_util: Number of GPUs with valid utilization data

    Returns:
        Tuple containing current_gpu_utilization, current_vram_utilization
    """
    total_vram_util = 0.0
    vram_count_for_util = 0

    for worker in workers:
        if worker.status and worker.status.gpu_devices:
            for gpu in worker.status.gpu_devices:
                if gpu.memory and gpu.memory.utilization_rate is not None:
                    total_vram_util += gpu.memory.utilization_rate
                    vram_count_for_util += 1

    # Calculate current utilization from worker status
    current_gpu_utilization = (
        total_gpu_util / gpu_count_for_util if gpu_count_for_util > 0 else 0.0
    )
    current_vram_utilization = (
        total_vram_util / vram_count_for_util if vram_count_for_util > 0 else 0.0
    )

    return current_gpu_utilization, current_vram_utilization


async def _calculate_gpu_monthly_change(session, workers, fields):
    """
    Calculate GPU count change month-over-month.

    Args:
        session: Database session
        workers: List of current Worker objects
        fields: Filter fields for workers

    Returns:
        GPU count change rate as percentage
    """
    # Calculate GPU change month-over-month
    now = datetime.now(timezone.utc)
    last_month_start = now - timedelta(days=30)

    # Get workers created before last month
    last_month_workers = await Worker.all_by_fields(
        session, fields=fields, extra_conditions=[Worker.created_at < last_month_start]
    )

    # Calculate GPU count for last month
    gpu_count_last_month = 0
    for worker in last_month_workers:
        if worker.status and worker.status.gpu_devices:
            gpu_count_last_month += len(worker.status.gpu_devices)

    # Calculate current GPU total
    gpu_total = 0
    for worker in workers:
        if worker.status and worker.status.gpu_devices:
            gpu_total += len(worker.status.gpu_devices)

    # Calculate month-over-month growth rate (percentage)
    if gpu_count_last_month == 0:
        if gpu_total == 0:
            # No change if both months have 0 GPUs
            gpu_change_month = 0.0
        else:
            # If last month had 0 GPUs, growth rate is (current / 1) * 100% (e.g., 0→8 = 800%)
            gpu_change_month = gpu_total * 100.0
    else:
        # Calculate growth rate as percentage change
        gpu_change_month = (
            (gpu_total - gpu_count_last_month) / gpu_count_last_month
        ) * 100

    # Round to one decimal place
    return round(gpu_change_month, 1)


async def _count_gpu_error_devices(session, workers):
    """
    Count GPU devices with error logs and compare with yesterday.

    Args:
        session: Database session
        workers: List of Worker objects

    Returns:
        Tuple containing:
        - gpu_error_device_count: Number of GPU devices with error logs today
        - gpu_error_device_change_day: Change in error devices from yesterday
    """
    from gpustack.schemas.load import GPULog

    # Get current time and calculate 24-hour periods
    now = datetime.now(timezone.utc)

    # Calculate today's period (last 24 hours from now)
    today_start = now - timedelta(days=1)
    today_end = now

    # Calculate yesterday's period (24-48 hours ago from now)
    yesterday_start = now - timedelta(days=2)
    yesterday_end = now - timedelta(days=1)

    # Convert to timestamps for query
    today_start_ts = int(today_start.timestamp())
    today_end_ts = int(today_end.timestamp())
    yesterday_start_ts = int(yesterday_start.timestamp())
    yesterday_end_ts = int(yesterday_end.timestamp())

    # Get worker IDs for filtering
    worker_ids = [worker.id for worker in workers] if workers else []

    # Count unique GPU IDs with error logs today
    today_error_gpu_ids = set()
    if worker_ids:
        today_statement = (
            select(GPULog.gpu_id)
            .where(GPULog.worker_id.in_(worker_ids))
            .where(GPULog.timestamp >= today_start_ts)
            .where(GPULog.timestamp <= today_end_ts)
            .where(GPULog.severity == "error")
        )
        today_error_gpus = (await session.exec(today_statement)).all()
        today_error_gpu_ids = set(today_error_gpus)

    # Count unique GPU IDs with error logs yesterday
    yesterday_error_gpu_ids = set()
    if worker_ids:
        yesterday_statement = (
            select(GPULog.gpu_id)
            .where(GPULog.worker_id.in_(worker_ids))
            .where(GPULog.timestamp >= yesterday_start_ts)
            .where(GPULog.timestamp <= yesterday_end_ts)
            .where(GPULog.severity == "error")
        )
        yesterday_error_gpus = (await session.exec(yesterday_statement)).all()
        yesterday_error_gpu_ids = set(yesterday_error_gpus)

    # Calculate counts
    today_count = len(today_error_gpu_ids)
    yesterday_count = len(yesterday_error_gpu_ids)

    # Calculate change from yesterday
    change_day = today_count - yesterday_count

    return today_count, change_day


async def _calculate_utilization_changes(session, workers):
    """
    Calculate day-over-day utilization changes from worker_loads table.

    Args:
        session: Database session
        workers: List of Worker objects

    Returns:
        Tuple containing gpu_utilization_change_day, vram_utilization_change_day
    """
    # Get current time and calculate 24-hour periods
    now = datetime.now(timezone.utc)

    # Calculate today's period (last 24 hours from now)
    today_start = now - timedelta(days=1)
    today_end = now

    # Calculate yesterday's period (24-48 hours ago from now)
    yesterday_start = now - timedelta(days=2)
    yesterday_end = now - timedelta(days=1)

    # Convert to timestamps for query
    today_start_ts = int(today_start.timestamp())
    today_end_ts = int(today_end.timestamp())
    yesterday_start_ts = int(yesterday_start.timestamp())
    yesterday_end_ts = int(yesterday_end.timestamp())

    # Get worker IDs for filtering
    worker_ids = [worker.id for worker in workers] if workers else []

    # Query today's worker loads
    today_worker_loads = []
    if worker_ids:
        today_statement = (
            select(WorkerLoad)
            .where(WorkerLoad.worker_id.in_(worker_ids))
            .where(WorkerLoad.timestamp >= today_start_ts)
            .where(WorkerLoad.timestamp <= today_end_ts)
        )
        today_worker_loads = (await session.exec(today_statement)).all()

    # Query yesterday's worker loads
    yesterday_worker_loads = []
    if worker_ids:
        yesterday_statement = (
            select(WorkerLoad)
            .where(WorkerLoad.worker_id.in_(worker_ids))
            .where(WorkerLoad.timestamp >= yesterday_start_ts)
            .where(WorkerLoad.timestamp <= yesterday_end_ts)
        )
        yesterday_worker_loads = (await session.exec(yesterday_statement)).all()

    # Calculate average GPU/VRAM utilization for today
    today_avg_gpu = 0.0
    today_avg_vram = 0.0
    if today_worker_loads:
        today_gpu_sum = sum(load.gpu or 0 for load in today_worker_loads)
        today_vram_sum = sum(load.vram or 0 for load in today_worker_loads)
        today_avg_gpu = today_gpu_sum / len(today_worker_loads)
        today_avg_vram = today_vram_sum / len(today_worker_loads)

    # Calculate average GPU/VRAM utilization for yesterday
    yesterday_avg_gpu = 0.0
    yesterday_avg_vram = 0.0
    if yesterday_worker_loads:
        yesterday_gpu_sum = sum(load.gpu or 0 for load in yesterday_worker_loads)
        yesterday_vram_sum = sum(load.vram or 0 for load in yesterday_worker_loads)
        yesterday_avg_gpu = yesterday_gpu_sum / len(yesterday_worker_loads)
        yesterday_avg_vram = yesterday_vram_sum / len(yesterday_worker_loads)

    # Calculate day-over-day change rates (percentage)
    def calculate_change_rate(today_val, yesterday_val):
        """Calculate percentage change between today and yesterday values."""
        if yesterday_val == 0:
            if today_val == 0:
                # No change if both values are 0
                return 0.0
            else:
                # If yesterday was 0, change rate is (today / 1) * 100%
                return today_val * 100.0
        else:
            # Standard percentage change calculation
            return ((today_val - yesterday_val) / yesterday_val) * 100.0

    # Calculate utilization changes
    gpu_utilization_change_day = calculate_change_rate(today_avg_gpu, yesterday_avg_gpu)
    vram_utilization_change_day = calculate_change_rate(
        today_avg_vram, yesterday_avg_vram
    )

    return gpu_utilization_change_day, vram_utilization_change_day


@router.get("/real-time-stats")
async def real_time_stats(
    session: SessionDep,
    cluster_id: Optional[int] = None,
):
    """
    Get real-time statistics summary.
    This endpoint returns comprehensive real-time statistics including:
    - GPU count with month-over-month change
    - GPU utilization with day-over-day change
    - VRAM utilization with day-over-day change
    - GPU health with error log trends
    - Abnormal device count
    - Total memory
    - Average GPU temperature
    """
    from gpustack.schemas.dashboard import RealTimeStats

    # Get all workers
    fields = {"cluster_id": cluster_id} if cluster_id else {}
    workers = await Worker.all_by_fields(session, fields=fields)

    # Calculate basic stats
    (
        gpu_total,
        total_memory,
        gpu_temperatures,
        abnormal_devices,
        total_gpu_util,
        gpu_count_for_util,
    ) = await _get_basic_stats(workers)

    # Calculate current utilization
    current_gpu_utilization, current_vram_utilization = await _get_current_utilization(
        workers, total_gpu_util, gpu_count_for_util
    )

    # Calculate average GPU temperature
    avg_gpu_temperature = (
        sum(gpu_temperatures) / len(gpu_temperatures) if gpu_temperatures else 0.0
    )

    # Calculate GPU change month-over-month
    gpu_change_month = await _calculate_gpu_monthly_change(session, workers, fields)

    # Calculate utilization changes day-over-day
    gpu_utilization_change_day, vram_utilization_change_day = (
        await _calculate_utilization_changes(session, workers)
    )

    # Count GPU error devices and compare with yesterday
    gpu_error_device_count, gpu_error_device_change_day = (
        await _count_gpu_error_devices(session, workers)
    )

    # Calculate GPU health (placeholder logic: higher is better)
    gpu_health = (
        100.0 - (abnormal_devices / gpu_total * 100) if gpu_total > 0 else 100.0
    )

    # Placeholder for other changes
    health_change_day = 0.0  # Would compare error logs with yesterday
    abnormal_device_change_day = 0  # Would compare with yesterday

    # Create response
    return RealTimeStats(
        gpu_total=gpu_total,
        gpu_change_month=gpu_change_month,
        gpu_utilization=round(current_gpu_utilization, 1),
        gpu_utilization_change_day=round(gpu_utilization_change_day, 1),
        vram_utilization=round(current_vram_utilization, 1),
        vram_utilization_change_day=round(vram_utilization_change_day, 1),
        gpu_health=round(gpu_health, 1),
        health_change_day=health_change_day,
        abnormal_device_count=abnormal_devices,
        abnormal_device_change_day=abnormal_device_change_day,
        total_memory=total_memory,
        avg_gpu_temperature=round(avg_gpu_temperature, 1),
        gpu_error_device_count=gpu_error_device_count,
        gpu_error_device_change_day=gpu_error_device_change_day,
        task_count=0,  # Placeholder value as requested
        avg_network_latency=0.0,  # Placeholder value as requested
    )
