from fastapi import APIRouter, Depends, Query
from sqlmodel import select
from typing import List, Optional

from gpustack.api.exceptions import NotFoundException, AlreadyExistsException
from gpustack.server.deps import SessionDep, get_admin_user
from gpustack.schemas.model_catalog import (
    ModelCatalog,
    ModelCatalogCreate,
    ModelCatalogUpdate,
    ModelCatalogResponse,
    ModelCatalogList,
    ModelCatalogListParams,
    ModelCatalogSpec,
    ModelCatalogSpecCreate,
    ModelCatalogSpecUpdate,
    ModelCatalogSpecResponse,
)
from gpustack.schemas.users import User

router = APIRouter()


@router.post(
    "/model_catalog", response_model=ModelCatalogResponse, tags=["model_catalog"]
)
async def create_model_catalog(
    session: SessionDep,
    model_catalog_data: ModelCatalogCreate,
    current_user: User = Depends(get_admin_user),
):
    """创建模型目录"""
    # 检查模型名称是否已存在
    existing_model = session.exec(
        select(ModelCatalog).where(
            ModelCatalog.name == model_catalog_data.name,
            ModelCatalog.deleted_at is None,
        )
    ).first()

    if existing_model:
        raise AlreadyExistsException(f"模型 {model_catalog_data.name} 已存在")

    # 创建模型目录
    model_catalog = ModelCatalog.model_validate(model_catalog_data)

    # 处理规格列表
    specs = []
    for spec_data in model_catalog_data.specs:
        spec = ModelCatalogSpec.model_validate(spec_data)
        specs.append(spec)

    model_catalog.specs = specs

    # 保存到数据库
    session.add(model_catalog)
    session.commit()
    session.refresh(model_catalog)

    return model_catalog


@router.get("/model_catalog", response_model=ModelCatalogList, tags=["model_catalog"])
async def list_model_catalog(
    session: SessionDep,
    params: ModelCatalogListParams = Depends(),
    is_deployed: Optional[bool] = Query(None, description="是否已部署"),
    category: Optional[str] = Query(None, description="模型类别"),
    current_user: User = Depends(get_admin_user),
):
    """获取模型目录列表"""
    query = select(ModelCatalog).where(ModelCatalog.deleted_at is None)

    # 应用过滤条件
    if is_deployed is not None:
        query = query.where(ModelCatalog.is_deployed == is_deployed)

    if category:
        query = query.where(category in ModelCatalog.categories)

    # 应用排序
    if params.sort_by:
        query = query.order_by(
            getattr(ModelCatalog, params.sort_by, ModelCatalog.created_at)
        )
    else:
        query = query.order_by(ModelCatalog.created_at.desc())

    # 应用分页
    total = session.exec(
        select(ModelCatalog).where(ModelCatalog.deleted_at is None)
    ).count()
    offset = (params.page - 1) * params.page_size
    items = session.exec(query.offset(offset).limit(params.page_size)).all()

    return ModelCatalogList(
        items=items, total=total, page=params.page, page_size=params.page_size
    )


@router.get(
    "/model_catalog/{model_catalog_id}",
    response_model=ModelCatalogResponse,
    tags=["model_catalog"],
)
async def get_model_catalog(
    session: SessionDep,
    model_catalog_id: int,
    current_user: User = Depends(get_admin_user),
):
    """获取单个模型目录详情"""
    model_catalog = session.get(ModelCatalog, model_catalog_id)

    if not model_catalog or model_catalog.deleted_at:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    return model_catalog


@router.put(
    "/model_catalog/{model_catalog_id}",
    response_model=ModelCatalogResponse,
    tags=["model_catalog"],
)
async def update_model_catalog(
    session: SessionDep,
    model_catalog_id: int,
    model_catalog_data: ModelCatalogUpdate,
    current_user: User = Depends(get_admin_user),
):
    """更新模型目录"""
    model_catalog = session.get(ModelCatalog, model_catalog_id)

    if not model_catalog or model_catalog.deleted_at:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    # 更新模型目录字段
    update_data = model_catalog_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(model_catalog, field, value)

    session.commit()
    session.refresh(model_catalog)

    return model_catalog


@router.delete("/model_catalog/{model_catalog_id}", tags=["model_catalog"])
async def delete_model_catalog(
    session: SessionDep,
    model_catalog_id: int,
    current_user: User = Depends(get_admin_user),
):
    """删除模型目录"""
    model_catalog = session.get(ModelCatalog, model_catalog_id)

    if not model_catalog or model_catalog.deleted_at:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    # 软删除模型目录
    model_catalog.soft_delete(session)

    session.commit()

    return {"message": f"模型目录 ID {model_catalog_id} 已删除"}


@router.post(
    "/model_catalog/{model_catalog_id}/specs",
    response_model=ModelCatalogSpecResponse,
    tags=["model_catalog"],
)
async def create_model_catalog_spec(
    session: SessionDep,
    model_catalog_id: int,
    spec_data: ModelCatalogSpecCreate,
    current_user: User = Depends(get_admin_user),
):
    """为模型目录创建规格"""
    # 检查模型目录是否存在
    model_catalog = session.get(ModelCatalog, model_catalog_id)

    if not model_catalog or model_catalog.deleted_at:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    # 创建规格
    spec = ModelCatalogSpec.model_validate(spec_data)
    spec.model_catalog_id = model_catalog_id

    session.add(spec)
    session.commit()
    session.refresh(spec)

    return spec


@router.get(
    "/model_catalog/{model_catalog_id}/specs",
    response_model=List[ModelCatalogSpecResponse],
    tags=["model_catalog"],
)
async def list_model_catalog_specs(
    session: SessionDep,
    model_catalog_id: int,
    current_user: User = Depends(get_admin_user),
):
    """获取模型目录的所有规格"""
    # 检查模型目录是否存在
    model_catalog = session.get(ModelCatalog, model_catalog_id)

    if not model_catalog or model_catalog.deleted_at:
        raise NotFoundException(f"模型目录 ID {model_catalog_id} 不存在")

    # 获取规格列表
    specs = session.exec(
        select(ModelCatalogSpec).where(
            ModelCatalogSpec.model_catalog_id == model_catalog_id,
            ModelCatalogSpec.deleted_at is None,
        )
    ).all()

    return specs


@router.get(
    "/model_catalog/specs/{spec_id}",
    response_model=ModelCatalogSpecResponse,
    tags=["model_catalog"],
)
async def get_model_catalog_spec(
    session: SessionDep, spec_id: int, current_user: User = Depends(get_admin_user)
):
    """获取单个模型目录规格详情"""
    spec = session.get(ModelCatalogSpec, spec_id)

    if not spec or spec.deleted_at:
        raise NotFoundException(f"模型目录规格 ID {spec_id} 不存在")

    return spec


@router.put(
    "/model_catalog/specs/{spec_id}",
    response_model=ModelCatalogSpecResponse,
    tags=["model_catalog"],
)
async def update_model_catalog_spec(
    session: SessionDep,
    spec_id: int,
    spec_data: ModelCatalogSpecUpdate,
    current_user: User = Depends(get_admin_user),
):
    """更新模型目录规格"""
    spec = session.get(ModelCatalogSpec, spec_id)

    if not spec or spec.deleted_at:
        raise NotFoundException(f"模型目录规格 ID {spec_id} 不存在")

    # 更新规格字段
    update_data = spec_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(spec, field, value)

    session.commit()
    session.refresh(spec)

    return spec


@router.delete("/model_catalog/specs/{spec_id}", tags=["model_catalog"])
async def delete_model_catalog_spec(
    session: SessionDep, spec_id: int, current_user: User = Depends(get_admin_user)
):
    """删除模型目录规格"""
    spec = session.get(ModelCatalogSpec, spec_id)

    if not spec or spec.deleted_at:
        raise NotFoundException(f"模型目录规格 ID {spec_id} 不存在")

    # 软删除规格
    spec.soft_delete(session)

    session.commit()

    return {"message": f"模型目录规格 ID {spec_id} 已删除"}
