from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON
from sqlmodel import Field, Relationship, SQLModel, Column, ForeignKey, Integer

from gpustack.mixins import BaseModelMixin
from gpustack.schemas.common import ListParams, PaginatedList
from gpustack.schemas.users import User


class ModelCatalogBase(SQLModel):
    """模型目录基础结构"""

    name: str = Field(description="模型名称")
    description: Optional[str] = Field(default=None, description="模型描述")
    home: Optional[str] = Field(default=None, description="模型主页")
    icon: Optional[str] = Field(default=None, description="模型图标")
    size: Optional[float] = Field(default=None, description="模型大小")
    activated_size: Optional[float] = Field(default=None, description="激活大小")
    size_unit: Optional[str] = Field(default=None, description="大小单位")
    categories: List[str] = Field(
        default_factory=list, sa_type=JSON, description="模型类别"
    )
    capabilities: List[str] = Field(
        default_factory=list, sa_type=JSON, description="模型能力"
    )
    licenses: List[str] = Field(
        default_factory=list, sa_type=JSON, description="模型许可证"
    )
    release_date: Optional[date] = Field(default=None, description="发布日期")
    is_deployed: bool = Field(default=False, description="是否已部署")


class ModelCatalog(ModelCatalogBase, BaseModelMixin, table=True):
    """模型目录表"""

    __tablename__ = "model_catalog"
    id: Optional[int] = Field(default=None, primary_key=True)
    created_by: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=True),
        description="创建者ID",
    )
    tenant_id: Optional[int] = Field(default=None, description="租户ID")

    # 关系
    specs: List["ModelCatalogSpec"] = Relationship(
        back_populates="model_catalog", cascade_delete=True
    )
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "ModelCatalog.created_by == User.id",
            "lazy": "selectin",
            "uselist": False,
        }
    )


class ModelCatalogSpecBase(SQLModel):
    """模型目录规格基础结构"""

    mode: Optional[str] = Field(default=None, description="模式")
    quantization: Optional[str] = Field(default=None, description="量化方式")
    gpu_filters: Optional[Dict[str, Any]] = Field(
        default=None, sa_type=JSON, description="GPU过滤器"
    )
    source: Optional[str] = Field(default=None, description="模型来源")
    huggingface_repo_id: Optional[str] = Field(
        default=None, description="Hugging Face仓库ID"
    )
    huggingface_filename: Optional[str] = Field(
        default=None, description="Hugging Face文件名"
    )
    model_scope_model_id: Optional[str] = Field(
        default=None, description="ModelScope模型ID"
    )
    model_scope_file_path: Optional[str] = Field(
        default=None, description="ModelScope文件路径"
    )
    local_path: Optional[str] = Field(default=None, description="本地路径")
    backend: Optional[str] = Field(default=None, description="后端")
    backend_version: Optional[str] = Field(default=None, description="后端版本")
    backend_parameters: Optional[List[str]] = Field(
        default=None, sa_type=JSON, description="后端参数"
    )
    env: Optional[Dict[str, str]] = Field(
        default=None, sa_type=JSON, description="环境变量"
    )


class ModelCatalogSpec(ModelCatalogSpecBase, BaseModelMixin, table=True):
    """模型目录规格表"""

    __tablename__ = "model_catalog_spec"
    id: Optional[int] = Field(default=None, primary_key=True)
    model_catalog_id: int = Field(
        description="模型目录ID", foreign_key="model_catalog.id"
    )

    # 关系
    model_catalog: "ModelCatalog" = Relationship(back_populates="specs")


# Pydantic models for requests and responses


class ModelCatalogSpecCreate(ModelCatalogSpecBase):
    """创建模型目录规格请求"""

    pass


class ModelCatalogCreate(ModelCatalogBase):
    """创建模型目录请求"""

    specs: List[ModelCatalogSpecCreate] = Field(
        default_factory=list, description="模型规格列表"
    )
    created_by: Optional[int] = Field(default=None, description="创建者ID")
    tenant_id: Optional[int] = Field(default=None, description="租户ID")


class ModelCatalogUpdate(BaseModel):
    """更新模型目录请求"""

    name: Optional[str] = Field(default=None, description="模型名称")
    description: Optional[str] = Field(default=None, description="模型描述")
    home: Optional[str] = Field(default=None, description="模型主页")
    icon: Optional[str] = Field(default=None, description="模型图标")
    size: Optional[float] = Field(default=None, description="模型大小")
    activated_size: Optional[float] = Field(default=None, description="激活大小")
    size_unit: Optional[str] = Field(default=None, description="大小单位")
    categories: Optional[List[str]] = Field(default=None, description="模型类别")
    capabilities: Optional[List[str]] = Field(default=None, description="模型能力")
    licenses: Optional[List[str]] = Field(default=None, description="模型许可证")
    release_date: Optional[date] = Field(default=None, description="发布日期")
    is_deployed: Optional[bool] = Field(default=None, description="是否已部署")
    created_by: Optional[int] = Field(default=None, description="创建者ID")
    tenant_id: Optional[int] = Field(default=None, description="租户ID")


class ModelCatalogSpecUpdate(BaseModel):
    """更新模型目录规格请求"""

    mode: Optional[str] = Field(default=None, description="模式")
    quantization: Optional[str] = Field(default=None, description="量化方式")
    gpu_filters: Optional[Dict[str, Any]] = Field(default=None, description="GPU过滤器")
    source: Optional[str] = Field(default=None, description="模型来源")
    huggingface_repo_id: Optional[str] = Field(
        default=None, description="Hugging Face仓库ID"
    )
    huggingface_filename: Optional[str] = Field(
        default=None, description="Hugging Face文件名"
    )
    model_scope_model_id: Optional[str] = Field(
        default=None, description="ModelScope模型ID"
    )
    model_scope_file_path: Optional[str] = Field(
        default=None, description="ModelScope文件路径"
    )
    local_path: Optional[str] = Field(default=None, description="本地路径")
    backend: Optional[str] = Field(default=None, description="后端")
    backend_version: Optional[str] = Field(default=None, description="后端版本")
    backend_parameters: Optional[List[str]] = Field(
        default=None, description="后端参数"
    )
    env: Optional[Dict[str, str]] = Field(default=None, description="环境变量")


class ModelCatalogSpecResponse(ModelCatalogSpecBase):
    """模型目录规格响应"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class ModelCatalogResponse(ModelCatalogBase):
    """模型目录响应"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    created_by: Optional[int] = Field(default=None, description="创建者ID")
    created_by_username: Optional[str] = Field(default=None, description="创建者用户名")
    tenant_id: Optional[int] = Field(default=None, description="租户ID")
    specs: List[ModelCatalogSpecResponse] = Field(
        default_factory=list, description="模型规格列表"
    )


class ModelCatalogListParams(ListParams):
    """模型目录列表参数"""

    is_deployed: Optional[bool] = Field(default=None, description="是否已部署")
    category: Optional[str] = Field(default=None, description="模型类别")


class ModelCatalogList(PaginatedList):
    """模型目录列表响应"""

    items: List[ModelCatalogResponse] = Field(
        default_factory=list, description="模型目录列表"
    )
