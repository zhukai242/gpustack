import asyncio
import logging

from typing import Tuple, Dict, List
from sqlmodel.ext.asyncio.session import AsyncSession
from gpustack.schemas.workers import Worker
from gpustack.schemas.system_load import SystemLoad
from gpustack.schemas.load import (
    WorkerLoadCreate,
    GPULoadCreate,
    WorkerLogCreate,
    GPULogCreate,
)
from gpustack.server.db import get_engine
from gpustack.server.load_services import (
    WorkerLoadService,
    GPULoadService,
    WorkerLogService,
    GPULogService,
)

logger = logging.getLogger(__name__)


def workers_by_cluster_id(workers: List[Worker]) -> Dict[int, List[Worker]]:
    rtn: Dict[int, List[Worker]] = {}
    for worker in workers:
        if worker.cluster_id not in rtn:
            rtn[worker.cluster_id] = []
        rtn[worker.cluster_id].append(worker)
    return rtn


def _safe_cpu_rate(worker: Worker) -> float:
    if worker.status and worker.status.cpu and worker.status.cpu.utilization_rate:
        return worker.status.cpu.utilization_rate
    return 0.0


def _safe_memory_rate(worker: Worker) -> float:
    if worker.status and worker.status.memory and worker.status.memory.utilization_rate:
        return worker.status.memory.utilization_rate
    return 0.0


def compute_avg_cpu_memory_utilization_rate(
    workers: List[Worker],
) -> Dict[int | None, Tuple[float, float]]:
    rtn: Dict[int | None, Tuple[float, float]] = {
        None: (0, 0),
    }
    by_cluster = workers_by_cluster_id(workers)
    cpu_sum_value = 0
    memory_sum_value = 0
    for cluster_id, cluster_workers in by_cluster.items():
        cpu_value = sum(_safe_cpu_rate(worker) for worker in cluster_workers)
        memory_value = sum(_safe_memory_rate(worker) for worker in cluster_workers)
        rtn[cluster_id] = (
            cpu_value / len(cluster_workers),
            memory_value / len(cluster_workers),
        )
        cpu_sum_value += cpu_value
        memory_sum_value += memory_value

    if len(workers) > 0:
        cpu_rate = cpu_sum_value / len(workers)
        memory_rate = memory_sum_value / len(workers)
        rtn[None] = (cpu_rate, memory_rate)

    return rtn


def compute_avg_gpu_utilization_rate(
    workers: List[Worker],
) -> Dict[int | None, Tuple[float, float]]:
    by_cluster = workers_by_cluster_id(workers)
    rtn: Dict[int | None, Tuple[float, float]] = {}
    all_util_count = 0
    all_memory_count = 0
    all_util_sum_value = 0
    all_memory_sum_value = 0
    for cluster_id, cluster_workers in by_cluster.items():
        util_count = sum(
            1
            for worker in cluster_workers
            for gpu in worker.status.gpu_devices or []
            if gpu.core and gpu.core.utilization_rate is not None
        )

        memory_count = sum(
            1
            for worker in cluster_workers
            for gpu in worker.status.gpu_devices or []
            if gpu.memory and gpu.memory.utilization_rate is not None
        )

        util_sum_value = sum(
            gpu.core.utilization_rate
            for worker in cluster_workers
            for gpu in worker.status.gpu_devices or []
            if gpu.core and gpu.core.utilization_rate is not None
        )

        memory_sum_value = sum(
            gpu.memory.utilization_rate
            for worker in cluster_workers
            for gpu in worker.status.gpu_devices or []
            if gpu.memory and gpu.memory.utilization_rate is not None
        )
        util_rate = util_sum_value / util_count if util_count > 0 else 0
        memory_rate = memory_sum_value / memory_count if memory_count > 0 else 0
        rtn[cluster_id] = (util_rate, memory_rate)

        all_util_count += util_count
        all_memory_count += memory_count
        all_util_sum_value += util_sum_value
        all_memory_sum_value += memory_sum_value

    rtn[None] = (
        all_util_sum_value / all_util_count if all_util_count > 0 else 0,
        all_memory_sum_value / all_memory_count if all_memory_count > 0 else 0,
    )
    return rtn


def compute_system_load(workers: List[Worker]) -> List[SystemLoad]:
    workers = [worker for worker in workers if not worker.state.is_provisioning]
    cpu_memory_by_cluster = compute_avg_cpu_memory_utilization_rate(workers)
    gpu_vram_by_cluster = compute_avg_gpu_utilization_rate(workers)
    rtn: List[SystemLoad] = [
        SystemLoad(
            cluster_id=cluster_id,
            cpu=cpu_memory_by_cluster.get(cluster_id, (0, 0))[0],
            ram=cpu_memory_by_cluster.get(cluster_id, (0, 0))[1],
            gpu=gpu_vram_by_cluster.get(cluster_id, (0, 0))[0],
            vram=gpu_vram_by_cluster.get(cluster_id, (0, 0))[1],
        )
        for cluster_id in set(cpu_memory_by_cluster) | set(gpu_vram_by_cluster)
    ]
    return rtn


class SystemLoadCollector:
    def __init__(self, interval=60):
        self.interval = interval
        self._engine = get_engine()

    async def start(self):
        while True:
            await asyncio.sleep(self.interval)
            try:
                async with AsyncSession(self._engine) as session:
                    workers = await Worker.all(session=session)

                    # Collect system load information
                    system_loads = compute_system_load(workers)
                    # Collect worker loads and logs
                    worker_loads = await self._collect_worker_loads(workers)
                    gpu_loads = await self._collect_gpu_loads(workers)
                    worker_logs = await self._collect_worker_logs(workers)
                    gpu_logs = await self._collect_gpu_logs(workers)
                    # Save all loads and logs to database
                    await self._save_system_loads(session, system_loads)
                    await self._save_worker_loads(session, worker_loads)
                    await self._save_gpu_loads(session, gpu_loads)
                    await self._save_worker_logs(session, worker_logs)
                    await self._save_gpu_logs(session, gpu_logs)
                    await session.commit()
            except Exception as e:
                logger.error(f"Failed to collect system load: {e}")

    async def _collect_worker_loads(self, workers):
        """Collect worker loads from workers."""
        worker_loads = []
        for worker in workers:
            if worker.state.is_provisioning:
                continue
            # Create worker load record
            worker_load = WorkerLoadCreate(
                worker_id=worker.id,
                cpu=_safe_cpu_rate(worker),
                ram=_safe_memory_rate(worker),
                # For worker-level GPU/VRAM, we'll calculate the average
                gpu=None,
                vram=None,
            )
            worker_loads.append(worker_load)

            # Calculate average GPU/VRAM for this worker
            if worker.status and worker.status.gpu_devices:
                total_gpu_util = 0.0
                total_vram_util = 0.0
                valid_gpu_count = 0
                valid_vram_count = 0

                for _gpu_index, gpu in enumerate(worker.status.gpu_devices):
                    gpu_util = (
                        gpu.core.utilization_rate
                        if gpu.core and gpu.core.utilization_rate is not None
                        else None
                    )
                    vram_util = (
                        gpu.memory.utilization_rate
                        if gpu.memory and gpu.memory.utilization_rate is not None
                        else None
                    )

                    # Accumulate for worker-level average
                    if gpu_util is not None:
                        total_gpu_util += gpu_util
                        valid_gpu_count += 1
                    if vram_util is not None:
                        total_vram_util += vram_util
                        valid_vram_count += 1

                # Update worker load with average GPU/VRAM
                if valid_gpu_count > 0:
                    worker_load.gpu = total_gpu_util / valid_gpu_count
                if valid_vram_count > 0:
                    worker_load.vram = total_vram_util / valid_vram_count

        return worker_loads

    async def _collect_gpu_loads(self, workers):
        """Collect GPU loads from workers."""
        gpu_loads = []
        for worker in workers:
            if worker.state.is_provisioning:
                continue
            # Collect GPU loads if available
            if worker.status and worker.status.gpu_devices:
                for gpu_index, gpu in enumerate(worker.status.gpu_devices):
                    # Create individual GPU load record
                    gpu_util = (
                        gpu.core.utilization_rate
                        if gpu.core and gpu.core.utilization_rate is not None
                        else None
                    )
                    vram_util = (
                        gpu.memory.utilization_rate
                        if gpu.memory and gpu.memory.utilization_rate is not None
                        else None
                    )

                    # Generate GPU ID in format: worker_name:gpu_type:gpu_index
                    gpu_type = gpu.type if gpu.type else "unknown"
                    gpu_id = f"{worker.name}:{gpu_type}:{gpu_index}"

                    gpu_load = GPULoadCreate(
                        worker_id=worker.id,
                        gpu_index=gpu_index,
                        gpu_id=gpu_id,
                        gpu_utilization=gpu_util,
                        vram_utilization=vram_util,
                    )
                    gpu_loads.append(gpu_load)
        return gpu_loads

    async def _collect_worker_logs(self, workers):
        """Collect worker logs from workers."""
        worker_logs = []
        for worker in workers:
            if worker.state.is_provisioning:
                continue

            # Collect worker logs if available
            if hasattr(worker.status, 'log') and worker.status.log:
                for log_entry in worker.status.log:
                    worker_log = WorkerLogCreate(
                        worker_id=worker.id,
                        log_type=(
                            log_entry.get('type')
                            if isinstance(log_entry, dict)
                            else 'unknown'
                        ),
                        log_content=(
                            log_entry.get('content')
                            if isinstance(log_entry, dict)
                            else str(log_entry)
                        ),
                        severity=(
                            log_entry.get('severity')
                            if isinstance(log_entry, dict)
                            else 'info'
                        ),
                        status=(
                            log_entry.get('status')
                            if isinstance(log_entry, dict)
                            else 'unknown'
                        ),
                    )
                    worker_logs.append(worker_log)

        return worker_logs

    async def _collect_gpu_logs(self, workers):
        """Collect GPU logs from workers."""
        gpu_logs = []
        for worker in workers:
            if worker.state.is_provisioning:
                continue

            # Collect GPU logs if available
            if worker.status and worker.status.gpu_devices:
                for gpu_index, gpu in enumerate(worker.status.gpu_devices):
                    # Collect GPU logs if available
                    if hasattr(gpu, 'log') and gpu.log:
                        # Generate GPU ID for log
                        gpu_type = gpu.type if gpu.type else "unknown"
                        gpu_id = f"{worker.name}:{gpu_type}:{gpu_index}"

                        for log_entry in gpu.log:
                            gpu_log = GPULogCreate(
                                worker_id=worker.id,
                                gpu_index=gpu_index,
                                gpu_id=gpu_id,
                                log_type=(
                                    log_entry.get('type')
                                    if isinstance(log_entry, dict)
                                    else 'unknown'
                                ),
                                log_content=(
                                    log_entry.get('content')
                                    if isinstance(log_entry, dict)
                                    else str(log_entry)
                                ),
                                severity=(
                                    log_entry.get('severity')
                                    if isinstance(log_entry, dict)
                                    else 'info'
                                ),
                                status=(
                                    log_entry.get('status')
                                    if isinstance(log_entry, dict)
                                    else 'unknown'
                                ),
                            )
                            gpu_logs.append(gpu_log)

        return gpu_logs

    async def _save_system_loads(self, session, system_loads):
        """Save system loads to database."""
        for system_load in system_loads:
            await SystemLoad.create(session, system_load, auto_commit=False)

    async def _save_worker_loads(self, session, worker_loads):
        """Save worker loads to database."""
        if worker_loads:
            worker_load_service = WorkerLoadService(session)
            await worker_load_service.create_many(worker_loads)

    async def _save_gpu_loads(self, session, gpu_loads):
        """Save GPU loads to database."""
        if gpu_loads:
            gpu_load_service = GPULoadService(session)
            await gpu_load_service.create_many(gpu_loads)

    async def _save_worker_logs(self, session, worker_logs):
        """Save worker logs to database."""
        if worker_logs:
            worker_log_service = WorkerLogService(session)
            await worker_log_service.create_many(worker_logs)

    async def _save_gpu_logs(self, session, gpu_logs):
        """Save GPU logs to database."""
        if gpu_logs:
            gpu_log_service = GPULogService(session)
            await gpu_log_service.create_many(gpu_logs)
