from typing import List, Tuple
from sqlmodel.ext.asyncio.session import AsyncSession
from gpustack.schemas.workers import Worker
from gpustack.schemas.system_load import SystemLoad
from gpustack.schemas.load import (
    WorkerLoadCreate,
    GPULoadCreate,
    WorkerLogCreate,
    GPULogCreate,
)
from gpustack.server.load_services import (
    WorkerLoadService,
    GPULoadService,
    WorkerLogService,
    GPULogService,
)
from gpustack.server.system_load import _safe_cpu_rate, _safe_memory_rate


async def collect_worker_loads(
    workers: List[Worker],
) -> Tuple[List[WorkerLoadCreate], List[GPULoadCreate]]:
    """Collect worker and GPU load data from workers."""
    worker_loads = []
    gpu_loads = []

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

    return worker_loads, gpu_loads


async def collect_worker_logs(
    workers: List[Worker],
) -> Tuple[List[WorkerLogCreate], List[GPULogCreate]]:
    """Collect worker and GPU logs from workers."""
    worker_logs = []
    gpu_logs = []

    for worker in workers:
        if worker.state.is_provisioning:
            continue
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

        # Collect GPU logs if available
        if worker.status and worker.status.gpu_devices:
            for gpu_index, gpu in enumerate(worker.status.gpu_devices):
                # Generate GPU ID for log
                gpu_type = gpu.type if gpu.type else "unknown"
                gpu_id = f"{worker.name}:{gpu_type}:{gpu_index}"
                # 打印出来是否包含log属性，以及log属性的类型,以及对应的log属性值
                print(f"GPU {gpu_id} log attribute value: {gpu.log}")
                if hasattr(gpu, 'log') and gpu.log:

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

    return worker_logs, gpu_logs


async def save_system_loads(
    session: AsyncSession,
    system_loads: List[SystemLoad],
    worker_loads: List[WorkerLoadCreate],
    gpu_loads: List[GPULoadCreate],
    worker_logs: List[WorkerLogCreate],
    gpu_logs: List[GPULogCreate],
) -> None:
    """Save all collected system loads, worker loads, GPU loads, and logs to database."""
    # Save all loads and logs to database
    for system_load in system_loads:
        await SystemLoad.create(session, system_load, auto_commit=False)

    if worker_loads:
        worker_load_service = WorkerLoadService(session)
        await worker_load_service.create_many(worker_loads)

    if gpu_loads:
        gpu_load_service = GPULoadService(session)
        await gpu_load_service.create_many(gpu_loads)

    if worker_logs:
        worker_log_service = WorkerLogService(session)
        await worker_log_service.create_many(worker_logs)

    if gpu_logs:
        gpu_log_service = GPULogService(session)
        await gpu_log_service.create_many(gpu_logs)
