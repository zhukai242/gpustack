from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class TimeSeriesData(BaseModel):
    timestamp: int
    value: float


class CurrentSystemLoad(BaseModel):
    cpu: float
    ram: float
    gpu: float
    vram: float


class HistorySystemLoad(BaseModel):
    cpu: List[TimeSeriesData]
    ram: List[TimeSeriesData]
    gpu: List[TimeSeriesData]
    vram: List[TimeSeriesData]


class SystemLoadSummary(BaseModel):
    current: CurrentSystemLoad
    history: HistorySystemLoad


class ModelUsageUserSummary(BaseModel):
    user_id: int
    username: str
    prompt_token_count: int
    completion_token_count: int


class ModelUsageStats(BaseModel):
    api_request_history: List[TimeSeriesData]
    completion_token_history: List[TimeSeriesData]
    prompt_token_history: List[TimeSeriesData]


class ModelUsageSummary(ModelUsageStats):
    top_users: Optional[List[ModelUsageUserSummary]] = None


class ResourceClaim(BaseModel):
    ram: int  # in bytes
    vram: int  # in bytes


class ModelSummary(BaseModel):
    id: int
    name: str
    resource_claim: ResourceClaim
    instance_count: int
    token_count: int
    categories: Optional[List[str]] = None


class ResourceCounts(BaseModel):
    worker_count: int
    gpu_count: int
    model_count: int
    model_instance_count: int
    cluster_count: Optional[int] = None

    model_config = ConfigDict(protected_namespaces=())


class CurrentWorkerLoad(BaseModel):
    cpu: float
    ram: float
    gpu: float
    vram: float


class HistoryWorkerLoad(BaseModel):
    cpu: List[TimeSeriesData]
    ram: List[TimeSeriesData]
    gpu: List[TimeSeriesData]
    vram: List[TimeSeriesData]


class WorkerLoadSummary(BaseModel):
    current: CurrentWorkerLoad
    history: HistoryWorkerLoad


class CurrentGPULoad(BaseModel):
    gpu: float
    vram: float


class HistoryGPULoad(BaseModel):
    gpu: List[TimeSeriesData]
    vram: List[TimeSeriesData]


class GPULoadSummary(BaseModel):
    current: CurrentGPULoad
    history: HistoryGPULoad


class SystemSummary(BaseModel):
    cluster_id: Optional[int] = None
    resource_counts: ResourceCounts
    system_load: SystemLoadSummary
    model_usage: ModelUsageSummary
    active_models: List[ModelSummary]

    model_config = ConfigDict(protected_namespaces=())


class RealTimeStats(BaseModel):
    """Real-time statistics summary."""

    # Total GPU count with month-over-month change
    gpu_total: int
    gpu_change_month: float  # Positive for increase, negative for decrease (percentage)

    # GPU utilization with day-over-day change
    gpu_utilization: float  # Current GPU utilization percentage (average)
    gpu_utilization_change_day: float  # Percentage change from yesterday

    # VRAM utilization with day-over-day change
    vram_utilization: float  # Current VRAM utilization percentage (average)
    vram_utilization_change_day: float  # Percentage change from yesterday

    # GPU health with day-over-day change in error logs
    gpu_health: float  # Health score from 0-100
    health_change_day: float  # Percentage change in error logs from yesterday

    # Abnormal device count with day-over-day change
    abnormal_device_count: int
    abnormal_device_change_day: int  # Positive for increase, negative for decrease

    # Total memory from workers
    total_memory: int  # in bytes

    # Task count (placeholder)
    task_count: int = 0

    # Average network latency (placeholder)
    avg_network_latency: float = 0.0  # in milliseconds

    # Average GPU temperature
    avg_gpu_temperature: float  # in Celsius

    # GPU error device count with day-over-day change
    gpu_error_device_count: int  # Number of devices with error logs
    gpu_error_device_change_day: int  # Change in error devices from yesterday

    model_config = ConfigDict(protected_namespaces=())
