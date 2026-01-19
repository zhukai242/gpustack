from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field
from enum import Enum

from gpustack.mixins.active_record import ActiveRecordMixin


class LogTypeEnum(str, Enum):
    """Log type enumeration."""

    STORAGE = "storage"  # 存储子系统
    NETWORK = "net"  # 网络子系统
    DEVICE_DRIVER = "device_driver"  # 设备与驱动
    MEMORY = "memory"  # 内存管理
    KERNEL = "kernel"  # 内核故障
    HARDWARE = "hardware"  # 硬件故障


class WorkerLoad(SQLModel, ActiveRecordMixin, table=True):
    __tablename__ = 'worker_loads'
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now(timezone.utc).timestamp())
    )
    worker_id: int = Field(index=True, foreign_key="workers.id")
    # cpu utilization rate for this worker
    cpu: Optional[float] = Field(default=None)
    # ram utilization rate for this worker
    ram: Optional[float] = Field(default=None)
    # gpu utilization rate for this worker
    gpu: Optional[float] = Field(default=None)
    # vram utilization rate for this worker
    vram: Optional[float] = Field(default=None)


class GPULoad(SQLModel, ActiveRecordMixin, table=True):
    __tablename__ = 'gpu_loads'
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now(timezone.utc).timestamp())
    )
    worker_id: int = Field(index=True, foreign_key="workers.id")
    # gpu index on the worker
    gpu_index: int = Field(default=0)
    # gpu id in format: worker_name:gpu_type:gpu_index
    gpu_id: str = Field(index=True)
    # gpu utilization rate for this gpu device
    gpu_utilization: Optional[float] = Field(default=None)
    # vram utilization rate for this gpu device
    vram_utilization: Optional[float] = Field(default=None)


class WorkerLoadCreate(SQLModel):
    worker_id: int
    cpu: Optional[float] = None
    ram: Optional[float] = None
    gpu: Optional[float] = None
    vram: Optional[float] = None


class GPULoadCreate(SQLModel):
    worker_id: int
    gpu_index: int
    gpu_id: str
    gpu_utilization: Optional[float] = None
    vram_utilization: Optional[float] = None


class WorkerLog(SQLModel, ActiveRecordMixin, table=True):
    __tablename__ = 'worker_logs'
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now(timezone.utc).timestamp())
    )
    worker_id: int = Field(index=True, foreign_key="workers.id")
    # log type
    log_type: Optional[str] = Field(default=None)
    # log content
    log_content: Optional[str] = Field(default=None)
    # severity level: info, warning, error
    severity: Optional[str] = Field(default=None)
    # status
    status: Optional[str] = Field(default=None)
    # processor
    processor: Optional[str] = Field(default=None, description="处理人")
    # comment
    comment: Optional[str] = Field(default=None, description="处理意见")


class GPULog(SQLModel, ActiveRecordMixin, table=True):
    __tablename__ = 'gpu_logs'
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now(timezone.utc).timestamp())
    )
    worker_id: int = Field(index=True, foreign_key="workers.id")
    # gpu index on the worker
    gpu_index: int = Field(default=0)
    # gpu id in format: worker_name:gpu_type:gpu_index
    gpu_id: str = Field(index=True)
    # log type
    log_type: Optional[str] = Field(default=None)
    # log content
    log_content: Optional[str] = Field(default=None)
    # severity level: info, warning, error
    severity: Optional[str] = Field(default=None)
    # status
    status: Optional[str] = Field(default=None)
    # processor
    processor: Optional[str] = Field(default=None, description="处理人")
    # comment
    comment: Optional[str] = Field(default=None, description="处理意见")


class WorkerLogCreate(SQLModel):
    worker_id: int
    log_type: Optional[str] = None
    log_content: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    processor: Optional[str] = None
    comment: Optional[str] = None


class GPULogCreate(SQLModel):
    worker_id: int
    gpu_index: int
    gpu_id: str
    log_type: Optional[str] = None
    log_content: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    processor: Optional[str] = None
    comment: Optional[str] = None
