from datetime import datetime
from typing import Optional, List, TYPE_CHECKING, Dict, Any, ClassVar
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Relationship, Column, Integer, ForeignKey
import sqlalchemy as sa

from gpustack.mixins import BaseModelMixin
from gpustack.schemas.common import ListParams, PaginatedList

if TYPE_CHECKING:
    from gpustack.schemas.workers import Worker


class RackCreate(SQLModel):
    """Create a rack."""

    name: str
    cluster_id: int
    description: Optional[str] = None


class RackUpdate(SQLModel):
    """Update a rack."""

    name: Optional[str] = None
    description: Optional[str] = None


class RackBase(RackCreate):
    """Base rack model."""

    pass


class Rack(RackBase, BaseModelMixin, table=True):
    """Rack ORM model."""

    __tablename__ = "racks"
    __table_args__ = (
        sa.Index("idx_racks_deleted_at_created_at", "deleted_at", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    cluster_id: int = Field(
        sa_column=Column(Integer, ForeignKey("clusters.id", ondelete="CASCADE"))
    )

    # Relationships
    rack_workers: List["Worker"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}, back_populates="rack"
    )


class RackListParams(ListParams):
    """List racks parameters."""

    sortable_fields: ClassVar[List[str]] = [
        "name",
        "cluster_id",
        "created_at",
        "updated_at",
    ]


class RackPublic(RackBase):
    """Public rack model."""

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


RacksPublic = PaginatedList[RackPublic]


class GPUDeviceInfo(BaseModel):
    """GPU device information."""

    id: str  # GPU unique identifier (format: worker_name:gpu_type:gpu_index)
    index: Optional[int] = None
    device_index: Optional[int] = None
    device_chip_index: Optional[int] = None
    vendor: Optional[str] = None
    type: Optional[str] = None
    memory: Optional[Dict[str, Any]] = None
    core: Optional[Dict[str, Any]] = None


class WorkerWithGPUs(BaseModel):
    """Worker with GPU devices information."""

    id: int
    name: str
    state: Optional[str] = None
    ip: Optional[str] = None
    gpu_devices: List[GPUDeviceInfo] = Field(default_factory=list)
    gpus: int = Field(default=0)


class RackWithWorkersAndGPUs(BaseModel):
    """Rack with workers and GPU devices information."""

    id: int
    name: str
    cluster_id: int
    description: Optional[str] = None
    workers: List[WorkerWithGPUs] = Field(default_factory=list)
    total_workers: int = Field(default=0)
    total_gpus: int = Field(default=0)


class RacksWithWorkersAndGPUs(BaseModel):
    """List of racks with workers and GPU devices information."""

    racks: List[RackWithWorkersAndGPUs] = Field(default_factory=list)


class ComparisonData(BaseModel):
    """Comparison data with previous period."""

    current: int
    previous: int
    growth: float  # positive for increase, negative for decrease


class UtilizationData(BaseModel):
    """Resource utilization data."""

    cpu: float = Field(default=0.0)
    ram: float = Field(default=0.0)
    gpu: float = Field(default=0.0)
    vram: float = Field(default=0.0)


class AlertData(BaseModel):
    """Alert events data."""

    total: int = Field(default=0)
    unprocessed: int = Field(default=0)
    comparison: ComparisonData = Field(default_factory=ComparisonData)


class ClusterStats(BaseModel):
    """Cluster statistics data."""

    total_workers: ComparisonData = Field(default_factory=ComparisonData)
    online_workers: ComparisonData = Field(default_factory=ComparisonData)
    offline_workers: ComparisonData = Field(default_factory=ComparisonData)
    utilization: UtilizationData = Field(default_factory=UtilizationData)
    alerts: AlertData = Field(default_factory=AlertData)
    resource_saturation: float = Field(default=0.0)


class RackGPUUtilization(BaseModel):
    """Rack-level GPU utilization statistics."""

    rack_id: int  # Rack ID
    rack_name: str  # Rack name
    avg_gpu_utilization: float  # Average GPU utilization percentage
    avg_vram_utilization: float  # Average VRAM utilization percentage


class RackGPUUtilizationResponse(BaseModel):
    """Response for rack GPU utilization statistics."""

    rack_gpu_utilizations: List[RackGPUUtilization] = Field(default_factory=list)


class GPUModelUtilization(BaseModel):
    """GPU model-level utilization statistics."""

    gpu_type: str  # GPU model/type
    count: int  # Number of GPUs of this type
    avg_gpu_utilization: float  # Average GPU utilization percentage for this model
    avg_vram_utilization: float  # Average VRAM utilization percentage for this model


class RackGPUModelUtilization(BaseModel):
    """Rack-level GPU model utilization statistics."""

    rack_id: int  # Rack ID
    rack_name: str  # Rack name
    gpu_models: List[GPUModelUtilization] = Field(default_factory=list)


class RackGPUModelUtilizationResponse(BaseModel):
    """Response for rack GPU model utilization statistics."""

    rack_gpu_model_utilizations: List[RackGPUModelUtilization] = Field(
        default_factory=list
    )


class GPUHeatmapData(BaseModel):
    """GPU device heatmap data."""

    index: int  # GPU index on the worker
    device_id: str  # GPU unique identifier
    gpu_utilization: float  # GPU utilization percentage
    vram_utilization: float  # VRAM utilization percentage
    gpu_type: str  # GPU model/type


class NodeHeatmapData(BaseModel):
    """Node (worker) level heatmap data."""

    node_id: int  # Worker ID
    node_name: str  # Worker name
    rack_id: int  # Rack ID
    rack_name: str  # Rack name
    cpu_utilization: float  # CPU utilization percentage
    ram_utilization: float  # RAM utilization percentage
    gpus: List[GPUHeatmapData]  # List of GPU devices with utilization


class RackHeatmapData(BaseModel):
    """Rack level heatmap data."""

    rack_id: int  # Rack ID
    rack_name: str  # Rack name
    nodes: List[NodeHeatmapData]  # List of nodes in this rack


class HeatmapResponse(BaseModel):
    """Heatmap response containing both rack and node level data."""

    cluster_id: int  # Cluster ID
    rack_heatmap: Optional[List[RackHeatmapData]] = None  # Rack level heatmap data
    node_heatmap: Optional[List[NodeHeatmapData]] = None  # Node level heatmap data


class GPUModeHealthStats(BaseModel):
    """GPU model health statistics."""

    arch_family: str  # GPU architecture family
    gpu_type: str  # GPU model/type (for reference)
    count: int  # Number of GPUs of this architecture family
    avg_temperature: float  # Average temperature for this architecture family
    total_warnings: int  # Total warning logs for this architecture family
    total_errors: int  # Total error logs for this architecture family
    health_score: float  # Health score (0-100), higher is better


class RackGPUHealthStats(BaseModel):
    """Rack-level GPU health statistics by model."""

    rack_id: int  # Rack ID
    rack_name: str  # Rack name
    gpu_models: List[GPUModeHealthStats] = Field(
        default_factory=list
    )  # GPU model health stats


class RackGPUHealthResponse(BaseModel):
    """Response for rack GPU health statistics by model."""

    rack_gpu_health: List[RackGPUHealthStats] = Field(default_factory=list)
