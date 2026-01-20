from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
from sqlmodel import (
    SQLModel,
    Field as SQLField,
    Relationship,
    Column,
    Integer,
    ForeignKey,
    JSON,
)
import sqlalchemy as sa

from gpustack.mixins import BaseModelMixin
from gpustack.schemas.common import ListParams, PaginatedList


class TenantStatusEnum(str, Enum):
    """Tenant status enum."""

    ACTIVE = "active"  # Tenant created, resources allocated but not activated
    INUSE = "inuse"  # Resources are activated and in use
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    EXPIRED = "expired"


class ResourceAdjustmentTypeEnum(str, Enum):
    """Resource adjustment type enum."""

    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"
    RENEW = "renew"


# ============ Tenant Models ============


class TenantCreate(SQLModel):
    """Create a tenant."""

    name: str
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    resource_start_time: Optional[datetime] = None
    resource_end_time: Optional[datetime] = None
    status: TenantStatusEnum = TenantStatusEnum.ACTIVE
    description: Optional[str] = None
    labels: Optional[Dict[str, str]] = SQLField(sa_column=Column(JSON), default={})


class TenantUpdate(SQLModel):
    """Update a tenant."""

    name: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    resource_start_time: Optional[datetime] = None
    resource_end_time: Optional[datetime] = None
    status: Optional[TenantStatusEnum] = None
    description: Optional[str] = None
    labels: Optional[Dict[str, str]] = SQLField(sa_column=Column(JSON), default=None)


class TenantBase(TenantCreate):
    """Base tenant model."""

    pass


class Tenant(TenantBase, BaseModelMixin, table=True):
    """Tenant ORM model."""

    __tablename__ = "tenants"
    __table_args__ = (
        sa.Index("idx_tenants_deleted_at_created_at", "deleted_at", "created_at"),
        sa.Index("idx_tenants_status", "status"),
        sa.Index("idx_tenants_name", "name"),
    )

    id: Optional[int] = SQLField(default=None, primary_key=True)

    # Relationships
    tenant_resources: List["TenantResource"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="tenant",
        cascade_delete=True,
    )
    resource_adjustments: List["TenantResourceAdjustment"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="tenant",
        cascade_delete=True,
    )
    resource_usage_details: List["TenantResourceUsageDetail"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="tenant",
        cascade_delete=True,
    )
    user_groups: List["UserGroup"] = Relationship(  # type: ignore # noqa: F821
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="tenant",
        cascade_delete=True,
    )


class TenantListParams(ListParams):
    """List tenants parameters."""

    sortable_fields: list[str] = [
        "name",
        "status",
        "created_at",
        "updated_at",
        "resource_end_time",
    ]


class GPULoadData(BaseModel):
    """GPU load data for usage trend."""

    timestamp: int
    gpu_utilization: Optional[float] = None
    vram_utilization: Optional[float] = None


class GPUDetail(BaseModel):
    """GPU detail information."""

    gpu_id: str
    worker_id: int
    gpu_index: int
    gpu_type: str
    gpu_utilization: Optional[float] = None
    vram_utilization: Optional[float] = None
    usage_trend: List[GPULoadData] = Field(default_factory=list)


class NodeDetail(BaseModel):
    """Node detail information."""

    worker_id: int
    worker_name: str
    gpus: List[GPUDetail] = Field(default_factory=list)
    total_gpus: int = 0
    active_gpus: int = 0


class TenantResourceDetail(BaseModel):
    """Tenant resource detail information."""

    resource_id: int
    worker_id: int
    gpu_id: str
    gpu_type: str
    resource_start_time: Optional[datetime] = None
    resource_end_time: Optional[datetime] = None
    cumulative_usage_time: float = 0.0  # in hours
    current_gpu_utilization: Optional[float] = None
    current_vram_utilization: Optional[float] = None
    usage_trend: List[GPULoadData] = Field(default_factory=list)


class TenantPublic(TenantBase):
    """Public tenant model with resource details."""

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    gpu_details: List[GPUDetail] = Field(default_factory=list)
    node_details: List[NodeDetail] = Field(default_factory=list)
    resource_details: List[TenantResourceDetail] = Field(default_factory=list)


TenantsPublic = PaginatedList[TenantPublic]


# ============ Tenant Resource Models ============


class TenantResourceCreate(SQLModel):
    """Create a tenant resource allocation."""

    tenant_id: int
    worker_id: int
    gpu_id: Optional[str] = None  # GPU ID format: worker_name:gpu_type:gpu_index
    resource_start_time: Optional[datetime] = None
    resource_end_time: Optional[datetime] = None
    resource_config: Optional[Dict[str, Any]] = SQLField(
        sa_column=Column(JSON), default={}
    )


class TenantResourceUpdate(SQLModel):
    """Update a tenant resource allocation."""

    resource_start_time: Optional[datetime] = None
    resource_end_time: Optional[datetime] = None
    resource_config: Optional[Dict[str, Any]] = SQLField(
        sa_column=Column(JSON), default=None
    )


class TenantResourceBase(TenantResourceCreate):
    """Base tenant resource model."""

    pass


class TenantResource(TenantResourceBase, BaseModelMixin, table=True):
    """Tenant resource allocation ORM model."""

    __tablename__ = "tenant_resources"
    __table_args__ = (
        sa.Index(
            "idx_tenant_resources_deleted_at_created_at",
            "deleted_at",
            "created_at",
        ),
        sa.Index("idx_tenant_resources_tenant_id", "tenant_id"),
        sa.Index("idx_tenant_resources_worker_id", "worker_id"),
        sa.Index("idx_tenant_resources_gpu_id", "gpu_id"),
        sa.Index("idx_tenant_resources_end_time", "resource_end_time"),
    )

    id: Optional[int] = SQLField(default=None, primary_key=True)
    tenant_id: int = SQLField(
        sa_column=Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"))
    )
    worker_id: int = SQLField(
        sa_column=Column(Integer, ForeignKey("workers.id", ondelete="CASCADE"))
    )

    # Relationships
    tenant: Tenant = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="tenant_resources",
    )
    user_group_resources: List["UserGroupResource"] = Relationship(  # type: ignore # noqa: F821
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="tenant_resource",
        cascade_delete=True,
    )


class TenantResourceListParams(ListParams):
    """List tenant resources parameters."""

    sortable_fields: list[str] = [
        "tenant_id",
        "worker_id",
        "created_at",
        "resource_start_time",
        "resource_end_time",
    ]


class TenantResourcePublic(TenantResourceBase):
    """Public tenant resource model."""

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


TenantResourcesPublic = PaginatedList[TenantResourcePublic]


# ============ Tenant Resource Adjustment Models ============


class TenantResourceAdjustmentCreate(SQLModel):
    """Create a tenant resource adjustment record."""

    tenant_id: int
    adjustment_type: ResourceAdjustmentTypeEnum
    adjustment_time: datetime
    operator: Optional[str] = None  # User who performed the adjustment
    adjustment_details: Optional[Dict[str, Any]] = SQLField(
        sa_column=Column(JSON), default={}
    )
    reason: Optional[str] = None


class TenantResourceAdjustmentBase(TenantResourceAdjustmentCreate):
    """Base tenant resource adjustment model."""

    pass


class TenantResourceAdjustment(
    TenantResourceAdjustmentBase, BaseModelMixin, table=True
):
    """Tenant resource adjustment ORM model."""

    __tablename__ = "tenant_resource_adjustments"
    __table_args__ = (
        sa.Index(
            "idx_tenant_adjustments_deleted_at_created_at",
            "deleted_at",
            "created_at",
        ),
        sa.Index("idx_tenant_adjustments_tenant_id", "tenant_id"),
        sa.Index("idx_tenant_adjustments_time", "adjustment_time"),
        sa.Index("idx_tenant_adjustments_type", "adjustment_type"),
    )

    id: Optional[int] = SQLField(default=None, primary_key=True)
    tenant_id: int = SQLField(
        sa_column=Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"))
    )

    # Relationships
    tenant: Tenant = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="resource_adjustments",
    )


class TenantResourceAdjustmentListParams(ListParams):
    """List tenant resource adjustments parameters."""

    sortable_fields: list[str] = [
        "tenant_id",
        "adjustment_type",
        "adjustment_time",
        "created_at",
    ]


class TenantResourceAdjustmentPublic(TenantResourceAdjustmentBase):
    """Public tenant resource adjustment model."""

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


TenantResourceAdjustmentsPublic = PaginatedList[TenantResourceAdjustmentPublic]


# ============ Tenant Resource Usage Detail Models ============


class TenantResourceUsageDetailCreate(SQLModel):
    """Create a tenant resource usage detail record."""

    tenant_id: int
    usage_date: datetime  # The date for this usage record (daily granularity)
    worker_id: int
    gpu_id: Optional[str] = None  # GPU ID format: worker_name:gpu_type:gpu_index
    gpu_hours: float = 0.0  # GPU usage hours for this day
    gpu_utilization: float = 0.0  # Average GPU utilization rate (0-100)
    vram_usage_gb: float = 0.0  # Average VRAM usage in GB
    cost: float = 0.0  # Cost generated for this day
    cost_currency: str = "USD"
    usage_metrics: Optional[Dict[str, Any]] = SQLField(
        sa_column=Column(JSON), default={}
    )


class TenantResourceUsageDetailBase(TenantResourceUsageDetailCreate):
    """Base tenant resource usage detail model."""

    pass


class TenantResourceUsageDetail(
    TenantResourceUsageDetailBase, BaseModelMixin, table=True
):
    """Tenant resource usage detail ORM model."""

    __tablename__ = "tenant_resource_usage_details"
    __table_args__ = (
        sa.Index(
            "idx_tenant_usage_deleted_at_created_at",
            "deleted_at",
            "created_at",
        ),
        sa.Index("idx_tenant_usage_tenant_id", "tenant_id"),
        sa.Index("idx_tenant_usage_date", "usage_date"),
        sa.Index("idx_tenant_usage_worker_id", "worker_id"),
        sa.Index("idx_tenant_usage_gpu_id", "gpu_id"),
        # Composite index for queries
        sa.Index("idx_tenant_usage_tenant_date", "tenant_id", "usage_date"),
    )

    id: Optional[int] = SQLField(default=None, primary_key=True)
    tenant_id: int = SQLField(
        sa_column=Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"))
    )
    worker_id: int = SQLField(
        sa_column=Column(Integer, ForeignKey("workers.id", ondelete="CASCADE"))
    )

    # Relationships
    tenant: Tenant = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="resource_usage_details",
    )


class TenantResourceUsageDetailListParams(ListParams):
    """List tenant resource usage details parameters."""

    sortable_fields: list[str] = [
        "tenant_id",
        "usage_date",
        "worker_id",
        "gpu_hours",
        "cost",
        "created_at",
    ]


class TenantResourceUsageDetailPublic(TenantResourceUsageDetailBase):
    """Public tenant resource usage detail model."""

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


TenantResourceUsageDetailsPublic = PaginatedList[TenantResourceUsageDetailPublic]


# ============ Extended Models with Relations ============


class TenantWithResources(BaseModel):
    """Tenant with allocated resources."""

    id: int
    name: str
    status: TenantStatusEnum
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    resource_start_time: Optional[datetime] = None
    resource_end_time: Optional[datetime] = None
    resources: List[TenantResourcePublic] = Field(default_factory=list)
    total_workers: int = Field(default=0)
    total_gpus: int = Field(default=0)


class TenantUsageSummary(BaseModel):
    """Tenant usage summary."""

    tenant_id: int
    tenant_name: str
    start_date: datetime
    end_date: datetime
    total_gpu_hours: float = 0.0
    average_gpu_utilization: float = 0.0
    total_cost: float = 0.0
    cost_currency: str = "USD"


class TenantResourceUtilization(BaseModel):
    """Tenant resource utilization for star chart."""

    tenant_id: int
    tenant_name: str
    gpu_count: int
    gpu_utilization: Optional[float] = None
    vram_utilization: Optional[float] = None


class TenantResourceUtilizationList(BaseModel):
    """List of tenant resource utilizations for star chart."""

    items: List[TenantResourceUtilization] = Field(default_factory=list)


class TenantResourceCounts(BaseModel):
    """Tenant resource counts."""

    gpu_total: int = Field(..., description="GPU总个数")
    gpu_used: int = Field(..., description="GPU当前已经使用量")
    gpu_utilization: float = Field(..., description="GPU当前使用率")
    vram_total: int = Field(..., description="显存总量")
    vram_used: int = Field(..., description="显存当前已经使用量")
    vram_utilization: float = Field(..., description="显存当前使用率")


class TenantSystemLoad(BaseModel):
    """Tenant system load summary."""

    current: Optional[Dict[str, Any]] = Field(None, description="当前系统负载")
    history: Optional[Dict[str, Any]] = Field(None, description="历史系统负载")


class TenantResourceStats(BaseModel):
    """Tenant resource statistics."""

    resource_counts: TenantResourceCounts = Field(..., description="资源统计")
    system_load: TenantSystemLoad = Field(..., description="系统负载")
