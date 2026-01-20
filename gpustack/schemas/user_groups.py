from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship, Column, Integer, ForeignKey, JSON
import sqlalchemy as sa

from gpustack.mixins import BaseModelMixin
from gpustack.schemas.common import ListParams, PaginatedList
from gpustack.schemas.tenants import Tenant
from gpustack.schemas.users import User
from gpustack.schemas.dashboard import TimeSeriesData


class UserGroupStatusEnum(str, Enum):
    """User group status enum."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


# ============ User Group Models ============


class UserGroupCreate(SQLModel):
    """Create a user group."""

    name: str
    tenant_id: int
    description: Optional[str] = None
    status: UserGroupStatusEnum = UserGroupStatusEnum.ACTIVE
    labels: Optional[Dict[str, str]] = Field(sa_column=Column(JSON), default={})
    member_ids: Optional[List[int]] = Field(
        default_factory=list, description="用户ID列表"
    )
    resource_ids: Optional[List[int]] = Field(
        default_factory=list, description="资源ID列表"
    )


class UserGroupUpdate(SQLModel):
    """Update a user group."""

    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[UserGroupStatusEnum] = None
    labels: Optional[Dict[str, str]] = Field(sa_column=Column(JSON), default=None)


class UserGroupBase(SQLModel):
    """Base user group model."""

    name: str
    tenant_id: int
    description: Optional[str] = None
    status: UserGroupStatusEnum = UserGroupStatusEnum.ACTIVE
    labels: Optional[Dict[str, str]] = Field(sa_column=Column(JSON), default={})


class UserGroup(UserGroupBase, BaseModelMixin, table=True):
    """User group ORM model."""

    __tablename__ = "user_groups"
    __table_args__ = (
        sa.Index("idx_user_groups_deleted_at_created_at", "deleted_at", "created_at"),
        sa.Index("idx_user_groups_tenant_id", "tenant_id"),
        sa.Index("idx_user_groups_status", "status"),
        sa.Index("idx_user_groups_name", "name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(
        sa_column=Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"))
    )

    # Relationships
    tenant: Tenant = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="user_groups",
    )
    members: List["UserGroupMember"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="user_group",
        cascade_delete=True,
    )
    resources: List["UserGroupResource"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="user_group",
        cascade_delete=True,
    )


class UserGroupListParams(ListParams):
    """List user groups parameters."""

    sortable_fields: list[str] = [
        "name",
        "status",
        "tenant_id",
        "created_at",
        "updated_at",
    ]


class UserGroupPublic(UserGroupBase):
    """Public user group model."""

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    member_count: Optional[int] = Field(default=0, description="成员数量")
    resource_count: Optional[int] = Field(default=0, description="资源数量")
    node_count: Optional[int] = Field(default=0, description="已分配节点数量")
    gpu_type_counts: Optional[Dict[str, int]] = Field(
        default_factory=dict, description="已分配卡类型和数量"
    )
    gpu_utilization: Optional[float] = Field(default=0.0, description="GPU使用率")
    vram_utilization: Optional[float] = Field(default=0.0, description="VRAM使用率")


class UserGroupDetail(UserGroupPublic):
    """User group detail model."""

    member_details: List[User] = Field(default_factory=list, description="成员详情")
    resource_details: List[Any] = Field(default_factory=list, description="资源详情")
    gpu_utilization_trend: List[TimeSeriesData] = Field(
        default_factory=list, description="GPU使用率趋势"
    )
    vram_utilization_trend: List[TimeSeriesData] = Field(
        default_factory=list, description="VRAM使用率趋势"
    )


class UserGroupStats(SQLModel):
    """User group statistics."""

    total_user_groups: int = Field(..., description="总用户组数")
    total_members: int = Field(..., description="总成员数")
    total_nodes: int = Field(..., description="总节点数（租户下）")
    total_gpus: int = Field(..., description="总卡数（租户下）")
    group_resource_usage: List[Dict[str, Any]] = Field(
        default_factory=list, description="各组资源占用情况"
    )


class UserGroupResourceUsage(SQLModel):
    """User group resource usage."""

    group_id: int
    group_name: str
    gpu_count: int
    gpu_utilization: float
    vram_utilization: float
    node_count: int


UserGroupsPublic = PaginatedList[UserGroupPublic]


# ============ User Group Member Models ============


class UserGroupMemberCreate(SQLModel):
    """Create a user group member."""

    user_group_id: int
    user_id: int


class UserGroupMemberBase(UserGroupMemberCreate):
    """Base user group member model."""

    pass


class UserGroupMember(UserGroupMemberBase, BaseModelMixin, table=True):
    """User group member ORM model."""

    __tablename__ = "user_group_members"
    __table_args__ = (
        sa.Index("idx_user_group_members_user_group_id", "user_group_id"),
        sa.Index("idx_user_group_members_user_id", "user_id"),
        sa.UniqueConstraint(
            "user_group_id",
            "user_id",
            name="uq_user_group_members_user_group_id_user_id",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_group_id: int = Field(
        sa_column=Column(Integer, ForeignKey("user_groups.id", ondelete="CASCADE"))
    )
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    )

    # Relationships
    user_group: UserGroup = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="members",
    )
    user: User = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="user_groups",
    )


# ============ User Group Resource Models ============


class UserGroupResourceCreate(SQLModel):
    """Create a user group resource."""

    user_group_id: int
    tenant_resource_id: int
    worker_id: int
    gpu_id: Optional[str] = None  # GPU ID format: worker_name:gpu_type:gpu_index


class UserGroupResourceBase(UserGroupResourceCreate):
    """Base user group resource model."""

    pass


class UserGroupResource(UserGroupResourceBase, BaseModelMixin, table=True):
    """User group resource ORM model."""

    __tablename__ = "user_group_resources"
    __table_args__ = (
        sa.Index("idx_user_group_resources_user_group_id", "user_group_id"),
        sa.Index("idx_user_group_resources_tenant_resource_id", "tenant_resource_id"),
        sa.Index("idx_user_group_resources_worker_id", "worker_id"),
        sa.Index("idx_user_group_resources_gpu_id", "gpu_id"),
        sa.UniqueConstraint(
            "user_group_id",
            "tenant_resource_id",
            name="uq_user_group_resources_user_group_id_tenant_resource_id",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_group_id: int = Field(
        sa_column=Column(Integer, ForeignKey("user_groups.id", ondelete="CASCADE"))
    )
    tenant_resource_id: int = Field(
        sa_column=Column(Integer, ForeignKey("tenant_resources.id", ondelete="CASCADE"))
    )
    worker_id: int = Field(
        sa_column=Column(Integer, ForeignKey("workers.id", ondelete="CASCADE"))
    )
    gpu_id: Optional[str] = Field(
        default=None
    )  # GPU ID format: worker_name:gpu_type:gpu_index

    # Relationships
    user_group: UserGroup = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="resources",
    )
    tenant_resource: "TenantResource" = Relationship(  # noqa: F821
        sa_relationship_kwargs={"lazy": "selectin"},
        back_populates="user_group_resources",
    )


# ============ User Group Resource Stats Models ============


class UserGroupResourceStats(SQLModel):
    """User group resource statistics."""

    group_id: int
    group_name: str
    gpu_count: int
    gpu_utilization: float
    vram_utilization: float
    node_count: int
    member_count: int


class UserGroupSummary(SQLModel):
    """User group summary for dashboard."""

    total_groups: int
    total_members: int
    total_nodes: int
    total_gpus: int
    group_stats: List[UserGroupResourceStats] = Field(default_factory=list)
