from datetime import datetime
from typing import Optional, List
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship
from gpustack.mixins import BaseModelMixin


class ReportTypeEnum(str, Enum):
    """Report type enum."""

    GPU = "gpu"
    WORKER = "worker"


class ReportStatusEnum(str, Enum):
    """Report status enum."""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportBase(SQLModel):
    """Base report model."""

    name: str
    type: ReportTypeEnum
    start_time: datetime
    end_time: datetime
    user_group_id: Optional[int] = None
    status: ReportStatusEnum = Field(default=ReportStatusEnum.PENDING)
    file_path: Optional[str] = None
    description: Optional[str] = None


class Report(ReportBase, BaseModelMixin, table=True):
    """Report model for database."""

    __tablename__ = "reports"
    id: Optional[int] = Field(default=None, primary_key=True)

    # Relationships
    details: List["ReportDetail"] = Relationship(
        back_populates="report",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class ReportDetailBase(SQLModel):
    """Base report detail model."""

    metric_name: str
    metric_value: float
    metric_unit: str
    timestamp: datetime
    resource_id: str
    resource_name: Optional[str] = None
    user_group_id: Optional[int] = None
    user_group_name: Optional[str] = None


class ReportDetail(ReportDetailBase, BaseModelMixin, table=True):
    """Report detail model for database."""

    __tablename__ = "report_details"
    id: Optional[int] = Field(default=None, primary_key=True)
    report_id: Optional[int] = Field(default=None, foreign_key="reports.id")

    # Relationships
    report: Optional[Report] = Relationship(back_populates="details")


class ReportCreate(ReportBase):
    """Report create model."""

    pass


class ReportUpdate(SQLModel):
    """Report update model."""

    status: Optional[ReportStatusEnum] = None
    file_path: Optional[str] = None
    description: Optional[str] = None


class ReportPublic(ReportBase):
    """Public report model for API response."""

    id: int
    created_at: datetime
    updated_at: datetime


class ReportDetailPublic(ReportDetailBase):
    """Public report detail model for API response."""

    id: int
    report_id: int


class ReportListParams(SQLModel):
    """Report list parameters."""

    page: int = Field(default=1, ge=1)
    perPage: int = Field(default=20, ge=1, le=100)
    order_by: str = Field(default="-created_at")
    type: Optional[ReportTypeEnum] = None
    status: Optional[ReportStatusEnum] = None
    user_group_id: Optional[int] = None


class ReportDetailsListParams(SQLModel):
    """Report details list parameters."""

    page: int = Field(default=1, ge=1)
    perPage: int = Field(default=20, ge=1, le=100)
    order_by: str = Field(default="timestamp")
    metric_name: Optional[str] = None
    resource_id: Optional[str] = None


class ReportsPublic(SQLModel):
    """Public report list model."""

    items: List[ReportPublic]
    total: int
    page: int
    perPage: int


class ReportDetailsPublic(SQLModel):
    """Public report details list model."""

    items: List[ReportDetailPublic]
    total: int
    page: int
    perPage: int


class ReportGenerateRequest(SQLModel):
    """Report generate request model."""

    type: ReportTypeEnum
    start_time: datetime
    end_time: datetime
    user_group_id: Optional[int] = None
    description: Optional[str] = None
