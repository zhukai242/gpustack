from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, List, Optional
from sqlalchemy import JSON, BigInteger
from sqlmodel import Field, Relationship, SQLModel, Text

from gpustack.schemas.common import (
    ListParams,
    PaginatedList,
)
from gpustack.mixins import BaseModelMixin

if TYPE_CHECKING:
    from gpustack.schemas.users import User


class DatasetCategoryEnum(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    MULTIMODAL = "multimodal"


class DatasetStorageTypeEnum(str, Enum):
    LOCAL = "local"
    S3 = "s3"
    GCS = "gcs"
    AZURE = "azure"
    HDFS = "hdfs"


class DatasetStatusEnum(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PROCESSING = "processing"
    ERROR = "error"


class DatasetBase(SQLModel):
    name: str = Field(index=True, unique=True)
    path: str = Field(max_length=1024)
    category: DatasetCategoryEnum = Field(sa_type=Text)
    tags: Optional[List[str]] = Field(sa_type=JSON, default=[])
    description: Optional[str] = Field(sa_type=Text, nullable=True)
    sample_count: Optional[int] = Field(default=0)
    size_bytes: Optional[int] = Field(default=0, sa_type=BigInteger)
    storage_type: Optional[DatasetStorageTypeEnum] = Field(
        default=DatasetStorageTypeEnum.LOCAL, sa_type=Text
    )
    status: Optional[DatasetStatusEnum] = Field(
        default=DatasetStatusEnum.ACTIVE, sa_type=Text
    )
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    updated_by: Optional[int] = Field(default=None, foreign_key="users.id")


class Dataset(DatasetBase, BaseModelMixin, table=True):
    __tablename__ = 'datasets'
    id: Optional[int] = Field(default=None, primary_key=True)

    versions: List["DatasetVersion"] = Relationship(
        back_populates="dataset",
        sa_relationship_kwargs={"cascade": "delete", "lazy": "noload"},
    )
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={"lazy": "noload", "foreign_keys": "Dataset.created_by"},
    )
    updater: Optional["User"] = Relationship(
        sa_relationship_kwargs={"lazy": "noload", "foreign_keys": "Dataset.updated_by"},
    )


class DatasetVersionBase(SQLModel):
    dataset_id: int = Field(foreign_key="datasets.id")
    version: str = Field(max_length=100)
    description: Optional[str] = Field(sa_type=Text, nullable=True)
    sample_count: Optional[int] = Field(default=0)
    size_bytes: Optional[int] = Field(default=0, sa_type=BigInteger)
    path: str = Field(max_length=1024)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    updated_by: Optional[int] = Field(default=None, foreign_key="users.id")


class DatasetVersion(DatasetVersionBase, BaseModelMixin, table=True):
    __tablename__ = 'dataset_versions'
    id: Optional[int] = Field(default=None, primary_key=True)

    dataset: Optional["Dataset"] = Relationship(
        back_populates="versions",
        sa_relationship_kwargs={"lazy": "noload"},
    )
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "lazy": "noload",
            "foreign_keys": "DatasetVersion.created_by",
        },
    )
    updater: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "lazy": "noload",
            "foreign_keys": "DatasetVersion.updated_by",
        },
    )


class DatasetListParams(ListParams):
    sortable_fields: ClassVar[List[str]] = [
        "name",
        "category",
        "sample_count",
        "size_bytes",
        "status",
        "created_at",
        "updated_at",
        "created_by",
    ]


class DatasetCreate(DatasetBase):
    pass


class DatasetUpdate(DatasetBase):
    pass


class DatasetPublic(DatasetBase):
    id: int
    created_at: datetime
    updated_at: datetime
    versions: List["DatasetVersionPublic"] = []


DatasetsPublic = PaginatedList[DatasetPublic]


class DatasetVersionListParams(ListParams):
    sortable_fields: ClassVar[List[str]] = [
        "version",
        "sample_count",
        "size_bytes",
        "created_at",
        "updated_at",
        "created_by",
    ]


class DatasetVersionCreate(DatasetVersionBase):
    pass


class DatasetVersionUpdate(DatasetVersionBase):
    pass


class DatasetVersionPublic(DatasetVersionBase):
    id: int
    created_at: datetime
    updated_at: datetime
    preview_url: Optional[str] = None


DatasetVersionsPublic = PaginatedList[DatasetVersionPublic]
