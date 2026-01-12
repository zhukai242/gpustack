from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, Column, JSON, Text
from pydantic import ConfigDict

from gpustack.mixins import BaseModelMixin
from gpustack.schemas.common import ListParams, PaginatedList


class SettingTypeEnum(str, Enum):
    """
    Enum for Setting Value Type
    """

    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    FLOAT = "float"
    JSON = "json"
    DATETIME = "datetime"


class SettingCategoryEnum(str, Enum):
    """
    Enum for Setting Category
    """

    BASIC = "basic"  # 基础设置
    NETWORK = "network"  # 网络设置
    SECURITY = "security"  # 安全设置
    STORAGE = "storage"  # 存储设置
    COMPUTE = "compute"  # 计算资源设置
    MONITORING = "monitoring"  # 监控配置
    LOGGING = "logging"  # 日志配置
    MAINTENANCE = "maintenance"  # 系统维护
    INTEGRATION = "integration"  # 集成配置
    ADVANCED = "advanced"  # 高级设置


class SystemSettingBase(SQLModel):
    """
    Base model for system settings
    """

    key: str = Field(..., index=True, unique=True, description="Setting key")
    value: Any = Field(..., sa_column=Column(JSON), description="Setting value")
    type: SettingTypeEnum = Field(..., description="Setting value type")
    category: SettingCategoryEnum = Field(
        default=SettingCategoryEnum.BASIC, description="Setting category"
    )
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text), description="Setting description"
    )
    is_required: bool = Field(
        default=False, description="Whether the setting is required"
    )
    is_editable: bool = Field(
        default=True, description="Whether the setting can be edited"
    )
    default_value: Optional[Any] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Default value for the setting",
    )
    labels: Optional[Dict[str, str]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Setting labels for categorization",
    )


class SystemSettingCreate(SystemSettingBase):
    """
    Model for creating a system setting
    """

    pass


class SystemSettingUpdate(SQLModel):
    """
    Model for updating a system setting
    """

    value: Optional[Any] = Field(default=None, sa_column=Column(JSON))
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    is_required: Optional[bool] = None
    is_editable: Optional[bool] = None
    default_value: Optional[Any] = Field(default=None, sa_column=Column(JSON))
    labels: Optional[Dict[str, str]] = Field(default=None, sa_column=Column(JSON))


class SystemSetting(SystemSettingBase, BaseModelMixin, table=True):
    """
    System Setting database model
    """

    __tablename__ = "system_settings"
    id: Optional[int] = Field(default=None, primary_key=True)


class SystemSettingPublic(SystemSettingBase):
    """
    Public model for system settings (response model)
    """

    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SystemSettingListParams(ListParams):
    """
    List parameters for system settings
    """

    sortable_fields: list[str] = Field(
        default_factory=lambda: [
            "key",
            "type",
            "is_required",
            "created_at",
            "updated_at",
        ]
    )
    filterable_fields: list[str] = Field(
        default_factory=lambda: ["key", "type", "is_required", "is_editable"]
    )


SystemSettingsPublic = PaginatedList[SystemSettingPublic]
