from datetime import datetime
from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Column, ForeignKey, Relationship
from sqlalchemy import Integer, String

from gpustack.mixins import BaseModelMixin
from gpustack.schemas.common import UTCDateTime, ListParams, PaginatedList


# Type imports for relationships
if TYPE_CHECKING:
    from .clusters import Cluster
    from .workers import Worker


class LicenseStatusEnum(str, Enum):
    """
    License状态枚举
    """

    ACTIVE = "active"  # 激活
    EXPIRED = "expired"  # 过期
    REVOKED = "revoked"  # 吊销
    SUSPENDED = "suspended"  # 暂停
    PENDING = "pending"  # 待激活

    @classmethod
    def _missing_(cls, value):
        """
        当枚举值不存在时，尝试从字符串值中查找匹配项
        解决数据库中存储小写值无法转换为枚举的问题
        """
        for member in cls:
            if member.value == value:
                return member
        return None


class LicenseOperationTypeEnum(str, Enum):
    """
    License操作类型枚举
    """

    CREATE = "create"  # 创建
    ACTIVATE = "activate"  # 激活
    REVOKE = "revoke"  # 吊销
    RENEW = "renew"  # 续期
    SUSPEND = "suspend"  # 暂停
    RESUME = "resume"  # 恢复
    UPDATE = "update"  # 更新
    DELETE = "delete"  # 删除

    @classmethod
    def _missing_(cls, value):
        """
        当枚举值不存在时，尝试从字符串值中查找匹配项
        解决数据库中存储小写值无法转换为枚举的问题
        """
        for member in cls:
            if member.value == value:
                return member
        return None


class LicenseTypeEnum(str, Enum):
    """
    License类型枚举
    """

    TRIAL = "trial"  # 试用版
    ENTERPRISE = "enterprise"  # 企业版
    STANDARD = "standard"  # 标准版
    PROFESSIONAL = "professional"  # 专业版

    @classmethod
    def _missing_(cls, value):
        """
        当枚举值不存在时，尝试从字符串值中查找匹配项
        解决数据库中存储小写值无法转换为枚举的问题
        """
        for member in cls:
            if member.value == value:
                return member
        return None


class LicenseBase(SQLModel):
    """
    License基础模型
    """

    license_id: str = Field(..., index=True, unique=True, description="License ID")
    license_code: str = Field(..., index=True, unique=True, description="License代码")
    license_type: LicenseTypeEnum = Field(
        default=LicenseTypeEnum.STANDARD,
        description="License类型",
        sa_column=Column(String),
    )
    status: LicenseStatusEnum = Field(
        default=LicenseStatusEnum.PENDING,
        description="License状态",
        sa_column=Column(String),
    )
    activation_time: Optional[datetime] = Field(
        sa_column=Column(UTCDateTime), default=None, description="激活时间"
    )
    expiration_time: Optional[datetime] = Field(
        sa_column=Column(UTCDateTime), default=None, description="到期时间"
    )
    issued_time: datetime = Field(
        sa_column=Column(UTCDateTime),
        default_factory=datetime.utcnow,
        description="颁发时间",
    )
    issuer: str = Field(default="system", description="颁发者")
    max_gpus: int = Field(default=0, description="最大GPU数量")
    cluster_id: Optional[int] = Field(
        sa_column=Column(
            Integer, ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True
        ),
        default=None,
        description="集群ID",
    )
    description: Optional[str] = Field(default=None, description="描述")


class LicenseCreate(LicenseBase):
    """
    License创建模型
    """

    pass


class LicenseUpdate(SQLModel):
    """
    License更新模型
    """

    status: Optional[LicenseStatusEnum] = None
    expiration_time: Optional[datetime] = None
    max_gpus: Optional[int] = None
    description: Optional[str] = None


class License(LicenseBase, BaseModelMixin, table=True):
    """
    License数据库模型
    """

    __tablename__ = "licenses"
    id: Optional[int] = Field(default=None, primary_key=True)

    # 关系
    cluster: Optional["Cluster"] = Relationship(back_populates="licenses")
    license_activations: List["LicenseActivation"] = Relationship(
        back_populates="license"
    )
    license_operations: List["LicenseOperation"] = Relationship(
        back_populates="license"
    )


class LicensePublic(LicenseBase):
    """
    License公开模型
    """

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    # 附加字段
    gpu_count: Optional[int] = Field(default=0, description="已激活GPU数量")


class LicenseActivationBase(SQLModel):
    """
    License激活基础模型
    """

    license_external_id: str = Field(..., index=True, description="External License ID")
    license_code: str = Field(..., index=True, description="License代码")
    license_id: Optional[int] = Field(description="License ID (Foreign Key)")
    worker_id: Optional[int] = Field(
        sa_column=Column(
            Integer, ForeignKey("workers.id", ondelete="SET NULL"), nullable=True
        ),
        description="Worker ID",
    )
    gpu_id: Optional[str] = Field(default=None, description="GPU ID")
    gpu_sn: str = Field(..., index=True, description="GPU序列号")
    gpu_model: Optional[str] = Field(default=None, description="GPU型号")
    status: LicenseStatusEnum = Field(
        default=LicenseStatusEnum.ACTIVE,
        description="激活状态",
        sa_column=Column(String),
    )
    activation_time: datetime = Field(
        sa_column=Column(UTCDateTime),
        default_factory=datetime.utcnow,
        description="激活时间",
    )
    expiration_time: Optional[datetime] = Field(
        sa_column=Column(UTCDateTime), description="到期时间"
    )
    activated_by: str = Field(default="system", description="激活者")


class LicenseActivationCreate(LicenseActivationBase):
    """
    License激活创建模型
    """

    pass


class LicenseActivationUpdate(SQLModel):
    """
    License激活更新模型
    """

    status: Optional[LicenseStatusEnum] = None
    expiration_time: Optional[datetime] = None


class LicenseActivation(LicenseActivationBase, BaseModelMixin, table=True):
    """
    License激活数据库模型
    """

    __tablename__ = "license_activations"
    id: Optional[int] = Field(default=None, primary_key=True)

    # 关系
    license_id: Optional[int] = Field(
        sa_column=Column(
            Integer, ForeignKey("licenses.id", ondelete="SET NULL"), nullable=True
        ),
        description="License ID",
    )
    license: Optional["License"] = Relationship(back_populates="license_activations")
    worker: Optional["Worker"] = Relationship(back_populates="license_activations")


class LicenseActivationPublic(LicenseActivationBase):
    """
    License激活公开模型
    """

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class BatchLicenseActivationRequest(SQLModel):
    """
    批量激活请求模型
    """

    activation_code: list[str] = Field(..., description="激活码列表")
    worker_id: int = Field(..., description="节点ID")


class BatchLicenseRenewalRequest(SQLModel):
    """
    批量续期请求模型
    """

    activation_code: list[str] = Field(..., description="激活码列表")
    worker_id: int = Field(..., description="节点ID")


class LicenseOperationBase(SQLModel):
    """
    License操作记录基础模型
    """

    license_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("licenses.id", ondelete="SET NULL"), nullable=True
        ),
        description="License ID",
    )
    operation_type: LicenseOperationTypeEnum = Field(
        ..., description="操作类型", sa_column=Column(String)
    )
    operator: str = Field(default="system", description="操作人")
    operation_time: datetime = Field(
        sa_column=Column(UTCDateTime),
        default_factory=datetime.utcnow,
        description="操作时间",
    )
    old_value: Optional[str] = Field(default=None, description="操作前的值（JSON格式）")
    new_value: Optional[str] = Field(default=None, description="操作后的值（JSON格式）")
    description: Optional[str] = Field(default=None, description="操作描述")


class LicenseOperationCreate(LicenseOperationBase):
    """
    License操作记录创建模型
    """

    pass


class LicenseOperation(LicenseOperationBase, BaseModelMixin, table=True):
    """
    License操作记录数据库模型
    """

    __tablename__ = "license_operations"
    id: Optional[int] = Field(default=None, primary_key=True)

    # 关系
    license: Optional["License"] = Relationship(back_populates="license_operations")


class LicenseOperationPublic(LicenseOperationBase):
    """
    License操作记录公开模型
    """

    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class LicenseListParams(ListParams):
    """
    License列表查询参数
    """

    sortable_fields: list[str] = Field(
        default_factory=lambda: [
            "license_id",
            "status",
            "license_type",
            "issued_time",
            "activation_time",
            "expiration_time",
            "created_at",
            "updated_at",
        ]
    )


class LicenseActivationListParams(ListParams):
    """
    License激活列表查询参数
    """

    sortable_fields: list[str] = Field(
        default_factory=lambda: [
            "license_id",
            "worker_id",
            "gpu_sn",
            "status",
            "activation_time",
            "expiration_time",
            "created_at",
            "updated_at",
        ]
    )


LicensesPublic = PaginatedList[LicensePublic]
LicenseActivationsPublic = PaginatedList[LicenseActivationPublic]
