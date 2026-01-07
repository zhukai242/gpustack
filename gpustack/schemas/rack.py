from datetime import datetime
from typing import Optional, List, TYPE_CHECKING, Dict, Any
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

    sortable_fields: list[str] = ["name", "cluster_id", "created_at", "updated_at"]


class RackPublic(RackBase):
    """Public rack model."""

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


RacksPublic = PaginatedList[RackPublic]


class GPUDeviceInfo(BaseModel):
    """GPU device information."""

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
