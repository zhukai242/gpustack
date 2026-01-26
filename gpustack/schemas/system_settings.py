from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, ClassVar, List, Type
from sqlmodel import SQLModel, Field, Column, JSON, Text
from sqlalchemy import TypeDecorator, String as sa_String
from pydantic import ConfigDict

from gpustack.mixins import BaseModelMixin
from gpustack.schemas.common import ListParams, PaginatedList


# 自定义类型转换器，处理字符串到枚举的转换
class StringToEnum(TypeDecorator):
    """
    TypeDecorator that converts strings to enum members, case-insensitively
    This is used when the database stores strings but we want to use enums in the model
    """

    impl = sa_String
    cache_ok = True

    def __init__(self, enum_class: Type[Enum], **kwargs):
        self.enum_class = enum_class
        super().__init__(**kwargs)

    def process_bind_param(self, value, dialect):
        """
        Convert enum member to string for database storage
        """
        if value is None:
            return None
        if isinstance(value, Enum):
            return value.value
        # If it's a string, convert to enum first then get its value
        return self.enum_class(value).value

    def process_result_value(self, value, dialect):
        """
        Convert string from database to enum member, case-insensitively
        """
        if value is None:
            return None

        # 移除可能存在的引号
        if isinstance(value, str):
            value = value.strip("'\"")

        # Case-insensitive matching
        value_lower = value.lower()
        for member in self.enum_class:
            if member.value.lower() == value_lower:
                return member

        # 如果没有找到匹配的枚举成员，返回第一个成员作为默认值
        return next(iter(self.enum_class))

    def copy(self, **kw):
        """
        Create a copy of this type instance
        """
        return StringToEnum(self.enum_class, **kw)


class SettingTypeEnum(str, Enum):
    """
    Enum for Setting Value Type
    """

    # Database stores uppercase values, but we need to support both cases
    STRING = "STRING"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    FLOAT = "FLOAT"
    JSON = "JSON"
    DATETIME = "DATETIME"

    @classmethod
    def _missing_(cls, value):
        """
        When the enum value is not found, try to match case-insensitively
        This handles the case where database stores uppercase values but code uses lowercase
        Also handles non-string values like booleans
        """
        if isinstance(value, bool):
            # For boolean values, return BOOLEAN enum member
            return cls.BOOLEAN

        if not isinstance(value, str):
            # For other non-string values, return first member as default
            return next(iter(cls))

        # Convert the value to uppercase to match database storage
        uppercase_value = value.upper()
        for member in cls:
            if member.value == uppercase_value:
                return member
        # 如果没有找到匹配的值，返回第一个有效成员作为默认值
        return next(iter(cls))


class SettingCategoryEnum(str, Enum):
    """
    Enum for Setting Category
    """

    BASIC = "BASIC"  # 基础设置
    NETWORK = "NETWORK"  # 网络设置
    SECURITY = "SECURITY"  # 安全设置
    STORAGE = "STORAGE"  # 存储设置
    COMPUTE = "COMPUTE"  # 计算资源设置
    MONITORING = "MONITORING"  # 监控配置
    LOGGING = "LOGGING"  # 日志配置
    MAINTENANCE = "MAINTENANCE"  # 系统维护
    INTEGRATION = "INTEGRATION"  # 集成配置
    ADVANCED = "ADVANCED"  # 高级设置

    @classmethod
    def _missing_(cls, value):
        """
        When the enum value is not found, try to match case-insensitively
        This handles the case where database stores uppercase values but code uses lowercase
        """
        if not isinstance(value, str):
            return None

        # Convert the value to uppercase to match database storage
        uppercase_value = value.upper()
        for member in cls:
            if member.value == uppercase_value:
                return member
        # 如果没有找到匹配的值，返回第一个有效成员作为默认值
        return cls(next(iter(cls)).value)


class SystemSettingBase(SQLModel):
    """
    Base model for system settings
    """

    key: str = Field(..., index=True, unique=True, description="Setting key")
    value: Any = Field(..., sa_column=Column(JSON), description="Setting value")
    type: SettingTypeEnum = Field(
        ..., sa_type=StringToEnum(SettingTypeEnum), description="Setting value type"
    )
    category: SettingCategoryEnum = Field(
        default=SettingCategoryEnum.BASIC,
        sa_type=StringToEnum(SettingCategoryEnum),
        description="Setting category",
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
    labels: Optional[Dict[str, Any]] = Field(
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
    labels: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


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

    type: Optional[str] = None
    key: Optional[str] = None
    is_required: Optional[bool] = None
    is_editable: Optional[bool] = None

    sortable_fields: ClassVar[List[str]] = [
        "key",
        "type",
        "is_required",
        "created_at",
        "updated_at",
    ]
    filterable_fields: ClassVar[List[str]] = [
        "key",
        "type",
        "is_required",
        "is_editable",
    ]


SystemSettingsPublic = PaginatedList[SystemSettingPublic]
