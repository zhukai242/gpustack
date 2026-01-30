from datetime import datetime
import os
import json
from typing import Optional, List, Dict, Any, Tuple
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from gpustack.config import get_global_config
from gpustack.api.exceptions import (
    AlreadyExistsException,
    InternalServerErrorException,
    NotFoundException,
)
from gpustack.server.deps import SessionDep, CurrentUserDep
from gpustack.schemas.datasets import (
    Dataset,
    DatasetBase,
    DatasetCreate,
    DatasetUpdate,
    DatasetPublic,
    DatasetsPublic,
    DatasetListParams,
    DatasetVersion,
    DatasetVersionCreate,
    DatasetVersionUpdate,
    DatasetVersionPublic,
    DatasetVersionsPublic,
    DatasetVersionListParams,
)


def calculate_directory_size(directory: str) -> int:
    """
    计算目录下所有文件的总大小（字节）

    Args:
        directory: 目录路径

    Returns:
        总大小（字节）
    """
    total_size = 0
    if not os.path.exists(directory):
        return total_size

    for root, _dirs, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                total_size += os.path.getsize(file_path)
            except OSError:
                # 忽略无法访问的文件
                pass
    return total_size


router = APIRouter()


async def _build_dataset_query(
    params: DatasetListParams,
    search: Optional[str],
    category: Optional[str],
    status: Optional[str],
) -> Tuple[Any, List[Any]]:
    """
    构建数据集查询语句

    Args:
        params: 分页和排序参数
        search: 搜索关键词
        category: 数据集类别过滤
        status: 数据集状态过滤

    Returns:
        查询语句和过滤条件列表
    """
    from sqlalchemy import select, and_, or_, func
    from sqlalchemy.sql import asc, desc

    statement = select(Dataset)
    conditions = []

    if category:
        conditions.append(Dataset.category == category)
    if status:
        conditions.append(Dataset.status == status)
    if search:
        search_conditions = [
            func.lower(Dataset.name).like(f"%{search.lower()}%"),
            func.lower(Dataset.description).like(f"%{search.lower()}%"),
        ]
        conditions.append(or_(*search_conditions))

    if conditions:
        statement = statement.where(and_(*conditions))

    order_by = params.order_by
    if not order_by:
        order_by = [("created_at", "desc")]

    for field, direction in order_by:
        column = getattr(Dataset, field)
        order_func = asc(column) if direction.lower() == "asc" else desc(column)
        statement = statement.order_by(order_func)

    return statement, conditions


async def _calculate_dataset_count(session: AsyncSession, conditions: List[Any]) -> int:
    """
    计算数据集总数

    Args:
        session: 数据库会话
        conditions: 过滤条件列表

    Returns:
        数据集总数
    """
    from sqlalchemy import select, and_, func

    count_statement = select(func.count(Dataset.id))
    if conditions:
        count_statement = count_statement.where(and_(*conditions))
    count_result = (await session.exec(count_statement)).one()

    if hasattr(count_result, '__len__') and len(count_result) > 0:
        return int(count_result[0])
    return int(count_result)


async def _get_dataset_versions(
    session: AsyncSession, dataset_id: int
) -> List[DatasetVersionPublic]:
    """
    获取数据集的版本信息

    Args:
        session: 数据库会话
        dataset_id: 数据集ID

    Returns:
        版本信息列表
    """
    from sqlalchemy import select, desc

    versions = []
    try:
        version_statement = select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id
        )
        version_statement = version_statement.order_by(desc(DatasetVersion.created_at))
        dataset_versions = (await session.exec(version_statement)).all()

        for version in dataset_versions:
            version_instance = _get_version_instance(version)
            preview_url = _generate_preview_url(version_instance)
            version_public = _build_version_public(version_instance, preview_url)
            versions.append(version_public)
    except Exception as e:
        print(f"Error getting versions for dataset {dataset_id}: {e}")

    return versions


def _get_version_instance(version: Any) -> Any:
    """
    获取版本实例，处理Row对象

    Args:
        version: 版本对象或Row对象

    Returns:
        DatasetVersion实例
    """
    version_instance = version
    if hasattr(version, '__len__') and len(version) > 0:
        try:
            version_instance = version[0]
        except (IndexError, TypeError):
            print(f"Invalid version Row object: {version}")
    return version_instance


def _generate_preview_url(version_instance: Any) -> Optional[str]:
    """
    生成预览URL

    Args:
        version_instance: DatasetVersion实例

    Returns:
        预览URL或None
    """
    preview_url = None
    version_path = getattr(version_instance, 'path', '')
    if version_path:
        config = get_global_config()
        storage_dir = getattr(config, 'storage_dir', '')
        if storage_dir and version_path.startswith(storage_dir):
            relative_path = version_path[len(storage_dir) :].lstrip('/')
            preview_url = f"/{relative_path}"
    return preview_url


def _build_version_public(
    version_instance: Any, preview_url: Optional[str]
) -> DatasetVersionPublic:
    """
    构建DatasetVersionPublic对象

    Args:
        version_instance: DatasetVersion实例
        preview_url: 预览URL

    Returns:
        DatasetVersionPublic对象
    """
    return DatasetVersionPublic(
        id=getattr(version_instance, 'id', 0),
        dataset_id=getattr(version_instance, 'dataset_id', 0),
        version=getattr(version_instance, 'version', ''),
        description=getattr(version_instance, 'description', ''),
        sample_count=getattr(version_instance, 'sample_count', 0),
        size_bytes=getattr(version_instance, 'size_bytes', 0),
        path=getattr(version_instance, 'path', ''),
        created_by=getattr(version_instance, 'created_by', None),
        updated_by=getattr(version_instance, 'updated_by', None),
        created_at=getattr(version_instance, 'created_at', datetime.now()),
        updated_at=getattr(version_instance, 'updated_at', datetime.now()),
        preview_url=preview_url,
    )


def _get_dataset_instance(dataset: Any) -> Any:
    """
    获取数据集实例，处理Row对象

    Args:
        dataset: 数据集对象或Row对象

    Returns:
        Dataset实例
    """
    dataset_instance = dataset
    if hasattr(dataset, '__len__') and len(dataset) > 0:
        try:
            dataset_instance = dataset[0]
        except (IndexError, TypeError):
            print(f"Invalid dataset Row object: {dataset}")
    return dataset_instance


def _build_dataset_public(
    dataset_instance: Any, versions: List[DatasetVersionPublic]
) -> DatasetPublic:
    """
    构建DatasetPublic对象

    Args:
        dataset_instance: Dataset实例
        versions: 版本信息列表

    Returns:
        DatasetPublic对象
    """
    return DatasetPublic(
        id=getattr(dataset_instance, 'id', 0),
        name=getattr(dataset_instance, 'name', 'Unknown'),
        path=getattr(dataset_instance, 'path', ''),
        category=getattr(dataset_instance, 'category', 'Unknown'),
        tags=getattr(dataset_instance, 'tags', []),
        description=getattr(dataset_instance, 'description', ''),
        sample_count=getattr(dataset_instance, 'sample_count', 0),
        size_bytes=getattr(dataset_instance, 'size_bytes', 0),
        storage_type=getattr(dataset_instance, 'storage_type', 'local'),
        status=getattr(dataset_instance, 'status', 'active'),
        created_by=getattr(dataset_instance, 'created_by', None),
        updated_by=getattr(dataset_instance, 'updated_by', None),
        created_at=getattr(dataset_instance, 'created_at', datetime.now()),
        updated_at=getattr(dataset_instance, 'updated_at', datetime.now()),
        versions=versions,
    )


def _build_pagination(page: int, per_page: int, count: int) -> Any:
    """
    构建分页信息

    Args:
        page: 当前页码
        per_page: 每页条数
        count: 总数

    Returns:
        分页对象
    """
    from gpustack.schemas.common import Pagination

    total_page = (count + per_page - 1) // per_page
    return Pagination(page=page, perPage=per_page, total=count, totalPage=total_page)


async def _process_dataset_item(
    session: SessionDep, dataset: Any
) -> Optional[DatasetPublic]:
    """
    处理单个数据集项

    Args:
        session: 数据库会话
        dataset: 数据集对象

    Returns:
        DatasetPublic对象或None
    """
    try:
        dataset_instance = _get_dataset_instance(dataset)
        dataset_id = getattr(dataset_instance, 'id', None)
        if dataset_id is None:
            print(f"Invalid dataset instance: {dataset_instance}")
            return None

        versions = await _get_dataset_versions(session, dataset_id)
        return _build_dataset_public(dataset_instance, versions)
    except Exception as e:
        print(f"Error processing dataset: {e}")
        return None


@router.get("", response_model=DatasetsPublic)
async def get_datasets(
    session: SessionDep,
    params: DatasetListParams = Depends(),
    search: Optional[str] = Query(
        None, description="Search datasets by name or description"
    ),
    category: Optional[str] = Query(None, description="Filter by dataset category"),
    status: Optional[str] = Query(None, description="Filter by dataset status"),
):
    """
    获取数据集列表

    Args:
        session: 数据库会话
        params: 分页和排序参数
        search: 搜索关键词
        category: 数据集类别过滤
        status: 数据集状态过滤

    Returns:
        分页的数据集列表，包含版本信息
    """
    try:
        # 构建查询语句
        statement, conditions = await _build_dataset_query(
            params, search, category, status
        )

        # 计算总数
        count = await _calculate_dataset_count(session, conditions)

        # 应用分页
        page = params.page
        per_page = params.perPage
        offset = (page - 1) * per_page
        statement = statement.offset(offset).limit(per_page)

        # 执行查询
        datasets = (await session.exec(statement)).all()

        # 构建返回结果
        items = []
        for dataset in datasets:
            dataset_public = await _process_dataset_item(session, dataset)
            if dataset_public:
                items.append(dataset_public)

        # 构建分页信息
        pagination = _build_pagination(page, per_page, count)
        return DatasetsPublic(items=items, pagination=pagination)
    except Exception as e:
        print(f"Error in get_datasets: {e}")
        # 简化实现，直接使用Dataset.paginated_by_query，不包含版本信息

        # 临时修改DatasetPublic，移除versions字段
        class SimpleDatasetPublic(DatasetBase):
            id: int
            created_at: datetime
            updated_at: datetime

        # 使用原始的paginated_by_query方法
        fuzzy_fields = {}
        if search:
            fuzzy_fields = {"name": search, "description": search}

        fields = {}
        if category:
            fields["category"] = category
        if status:
            fields["status"] = status

        result = await Dataset.paginated_by_query(
            session=session,
            fuzzy_fields=fuzzy_fields,
            extra_conditions=[],
            page=params.page,
            per_page=params.perPage,
            fields=fields,
            order_by=params.order_by,
        )

        # 转换结果
        simple_items = []
        for item in result.items:
            simple_item = SimpleDatasetPublic(**item.model_dump())
            simple_items.append(simple_item)

        return DatasetsPublic(items=simple_items, pagination=result.pagination)


@router.get("/{id}", response_model=DatasetPublic)
async def get_dataset(
    session: SessionDep,
    id: int,
):
    """
    获取单个数据集详情

    Args:
        session: 数据库会话
        id: 数据集ID

    Returns:
        数据集详情
    """
    dataset = await Dataset.one_by_id(session, id)
    if not dataset:
        raise NotFoundException(message="Dataset not found")

    return dataset


@router.post("", response_model=DatasetPublic)
async def create_dataset(
    session: SessionDep,
    dataset_in: DatasetCreate,
    current_user: CurrentUserDep,
):
    """
    创建新数据集

    Args:
        session: 数据库会话
        dataset_in: 数据集创建参数
        current_user: 当前用户

    Returns:
        创建的数据集详情
    """
    # 检查数据集名称是否已存在
    existing = await Dataset.one_by_field(session, "name", dataset_in.name)
    if existing:
        raise AlreadyExistsException(
            message=f"Dataset '{dataset_in.name}' already exists. "
            "Please choose a different name or check the existing dataset."
        )

    try:
        # 设置创建者和更新者
        dataset_in.created_by = current_user.id
        dataset_in.updated_by = current_user.id

        # 计算目录大小
        if dataset_in.path:
            dataset_in.size_bytes = calculate_directory_size(dataset_in.path)

        # 创建数据集
        dataset = await Dataset.create(session, dataset_in)

        # 创建默认版本
        version_in = DatasetVersionCreate(
            dataset_id=dataset.id,
            version="1.0.0",
            description=f"Initial version of {dataset.name}",
            sample_count=dataset.sample_count,
            size_bytes=dataset.size_bytes,
            path=dataset.path,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        await DatasetVersion.create(session, version_in)

    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to create dataset: {e}")

    return dataset


@router.put("/{id}", response_model=DatasetPublic)
async def update_dataset(
    session: SessionDep,
    id: int,
    dataset_in: DatasetUpdate,
    current_user: CurrentUserDep,
):
    """
    更新数据集

    Args:
        session: 数据库会话
        id: 数据集ID
        dataset_in: 数据集更新参数
        current_user: 当前用户

    Returns:
        更新后的数据集详情
    """
    dataset = await Dataset.one_by_id(session, id)
    if not dataset:
        raise NotFoundException(message="Dataset not found")

    # 检查名称是否与其他数据集冲突
    if dataset_in.name and dataset_in.name != dataset.name:
        existing = await Dataset.one_by_field(session, "name", dataset_in.name)
        if existing:
            raise AlreadyExistsException(
                message=f"Dataset '{dataset_in.name}' already exists. "
                "Please choose a different name or check the existing dataset."
            )

    try:
        # 设置更新者
        dataset_in.updated_by = current_user.id

        # 计算目录大小
        if dataset_in.path:
            dataset_in.size_bytes = calculate_directory_size(dataset_in.path)

        await Dataset.update(session, id, dataset_in)
        updated_dataset = await Dataset.one_by_id(session, id)
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to update dataset: {e}")

    return updated_dataset


@router.delete("/{id}")
async def delete_dataset(
    session: SessionDep,
    id: int,
):
    """
    删除数据集

    Args:
        session: 数据库会话
        id: 数据集ID
    """
    dataset = await Dataset.one_by_id(session, id)
    if not dataset:
        raise NotFoundException(message="Dataset not found")

    try:
        await Dataset.delete(session, id)
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to delete dataset: {e}")


# 数据集版本管理路由


@router.get("/{dataset_id}/versions", response_model=DatasetVersionsPublic)
async def get_dataset_versions(
    session: SessionDep,
    dataset_id: int,
    params: DatasetVersionListParams = Depends(),
    search: Optional[str] = Query(
        None, description="Search versions by version or description"
    ),
):
    """
    获取数据集版本列表

    Args:
        session: 数据库会话
        dataset_id: 数据集ID
        params: 分页和排序参数
        search: 搜索关键词

    Returns:
        分页的数据集版本列表
    """
    # 检查数据集是否存在
    dataset = await Dataset.one_by_id(session, dataset_id)
    if not dataset:
        raise NotFoundException(message="Dataset not found")

    fuzzy_fields = {}
    if search:
        fuzzy_fields = {"version": search, "description": search}

    fields = {"dataset_id": dataset_id}

    extra_conditions = []

    order_by = params.order_by

    return await DatasetVersion.paginated_by_query(
        session=session,
        fuzzy_fields=fuzzy_fields,
        extra_conditions=extra_conditions,
        page=params.page,
        per_page=params.perPage,
        fields=fields,
        order_by=order_by,
    )


@router.get("/{dataset_id}/versions/{version_id}", response_model=DatasetVersionPublic)
async def get_dataset_version(
    session: SessionDep,
    dataset_id: int,
    version_id: int,
):
    """
    获取单个数据集版本详情

    Args:
        session: 数据库会话
        dataset_id: 数据集ID
        version_id: 版本ID

    Returns:
        数据集版本详情
    """
    # 检查数据集是否存在
    dataset = await Dataset.one_by_id(session, dataset_id)
    if not dataset:
        raise NotFoundException(message="Dataset not found")

    # 检查版本是否存在且属于该数据集
    version = await DatasetVersion.one_by_id(session, version_id)
    if not version or version.dataset_id != dataset_id:
        raise NotFoundException(message="Dataset version not found")

    return version


@router.post("/{dataset_id}/versions", response_model=DatasetVersionPublic)
async def create_dataset_version(
    session: SessionDep,
    dataset_id: int,
    version_in: DatasetVersionCreate,
    current_user: CurrentUserDep,
):
    """
    创建数据集版本

    Args:
        session: 数据库会话
        dataset_id: 数据集ID
        version_in: 版本创建参数
        current_user: 当前用户

    Returns:
        创建的数据集版本详情
    """
    # 检查数据集是否存在
    dataset = await Dataset.one_by_id(session, dataset_id)
    if not dataset:
        raise NotFoundException(message="Dataset not found")

    # 检查版本号是否已存在
    existing = await DatasetVersion.one_by_fields(
        session, fields={"dataset_id": dataset_id, "version": version_in.version}
    )
    if existing:
        raise AlreadyExistsException(
            message=f"Version '{version_in.version}' already exists for dataset "
            f"'{dataset.name}'. Please choose a different version number or "
            "check the existing version."
        )

    try:
        # 设置创建者和更新者
        version_in.created_by = current_user.id
        version_in.updated_by = current_user.id
        # 确保dataset_id一致
        version_in.dataset_id = dataset_id

        # 计算目录大小
        if version_in.path:
            version_in.size_bytes = calculate_directory_size(version_in.path)

        version = await DatasetVersion.create(session, version_in)

        # 更新数据集主表的sample_count和size_bytes
        dataset_update = DatasetUpdate(
            sample_count=version_in.sample_count,
            size_bytes=version_in.size_bytes,
            updated_by=current_user.id,
        )
        await Dataset.update(session, dataset_id, dataset_update)
    except Exception as e:
        raise InternalServerErrorException(
            message=f"Failed to create dataset version: {e}"
        )

    return version


@router.put("/{dataset_id}/versions/{version_id}", response_model=DatasetVersionPublic)
async def update_dataset_version(
    session: SessionDep,
    dataset_id: int,
    version_id: int,
    version_in: DatasetVersionUpdate,
    current_user: CurrentUserDep,
):
    """
    更新数据集版本

    Args:
        session: 数据库会话
        dataset_id: 数据集ID
        version_id: 版本ID
        version_in: 版本更新参数
        current_user: 当前用户

    Returns:
        更新后的数据集版本详情
    """
    # 检查数据集是否存在
    dataset = await Dataset.one_by_id(session, dataset_id)
    if not dataset:
        raise NotFoundException(message="Dataset not found")

    # 检查版本是否存在且属于该数据集
    version = await DatasetVersion.one_by_id(session, version_id)
    if not version or version.dataset_id != dataset_id:
        raise NotFoundException(message="Dataset version not found")

    # 检查版本号是否与其他版本冲突
    if version_in.version and version_in.version != version.version:
        existing = await DatasetVersion.one_by_fields(
            session, fields={"dataset_id": dataset_id, "version": version_in.version}
        )
        if existing:
            raise AlreadyExistsException(
                message=f"Version '{version_in.version}' already exists for dataset "
                f"'{dataset.name}'. Please choose a different version number or "
                "check the existing version."
            )

    try:
        # 设置更新者
        version_in.updated_by = current_user.id
        # 确保dataset_id一致
        version_in.dataset_id = dataset_id

        # 计算目录大小
        if version_in.path:
            version_in.size_bytes = calculate_directory_size(version_in.path)

        await DatasetVersion.update(session, version_id, version_in)
        updated_version = await DatasetVersion.one_by_id(session, version_id)

        # 更新数据集主表的sample_count和size_bytes
        dataset_update = DatasetUpdate(
            sample_count=version_in.sample_count,
            size_bytes=version_in.size_bytes,
            updated_by=current_user.id,
        )
        await Dataset.update(session, dataset_id, dataset_update)
    except Exception as e:
        raise InternalServerErrorException(
            message=f"Failed to update dataset version: {e}"
        )

    return updated_version


def _build_category_map(categories: List[Dict[str, Any]]) -> Dict[int, str]:
    """
    构建类别映射

    Args:
        categories: 类别列表

    Returns:
        类别ID到名称的映射
    """
    return {cat['id']: cat['name'] for cat in categories}


def _build_image_annotations_map(
    annotations: List[Dict[str, Any]]
) -> Dict[int, List[Dict[str, Any]]]:
    """
    构建图片ID到标注的映射

    Args:
        annotations: 标注列表

    Returns:
        图片ID到标注列表的映射
    """
    image_annotations = {}
    # 限制处理的标注数量
    for ann in annotations[:1000]:
        img_id = ann['image_id']
        if img_id not in image_annotations:
            image_annotations[img_id] = []
        image_annotations[img_id].append(ann)
    return image_annotations


def _build_coco_preview_item(
    img: Dict[str, Any],
    image_annotations: Dict[int, List[Dict[str, Any]]],
    category_map: Dict[int, str],
) -> Dict[str, Any]:
    """
    构建单个COCO预览项

    Args:
        img: 图片信息
        image_annotations: 图片ID到标注的映射
        category_map: 类别ID到名称的映射

    Returns:
        预览项
    """
    item = {
        'id': img['id'],
        'file_name': img['file_name'],
        'width': img['width'],
        'height': img['height'],
        'annotations': [],
    }

    # 添加标注信息
    if img['id'] in image_annotations:
        for ann in image_annotations[img['id']][:5]:  # 每个图片最多显示5个标注
            ann_info = {
                'category_id': ann['category_id'],
                'category_name': category_map.get(ann['category_id'], 'Unknown'),
                'bbox': ann.get('bbox', []),
                'segmentation': ann.get('segmentation', []),
            }
            item['annotations'].append(ann_info)

    return item


def _process_coco_json_file(
    json_path: str, preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理单个COCO JSON文件

    Args:
        json_path: JSON文件路径
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            coco_data = json.load(f)

        # 提取图片和标注信息
        images = coco_data.get('images', [])
        annotations = coco_data.get('annotations', [])
        categories = coco_data.get('categories', [])

        # 构建类别映射
        category_map = _build_category_map(categories)

        # 构建图片ID到标注的映射
        image_annotations = _build_image_annotations_map(annotations)

        # 生成预览项
        for img in images[:limit]:
            if len(preview_items) >= limit:
                break
            item = _build_coco_preview_item(img, image_annotations, category_map)
            preview_items.append(item)
    except Exception as e:
        print(f"Error processing COCO file {os.path.basename(json_path)}: {e}")


async def preview_coco_dataset(
    dataset_path: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """
    预览COCO格式的图片数据集

    Args:
        dataset_path: 数据集路径
        limit: 预览条目数量

    Returns:
        预览数据列表
    """
    preview_items = []

    # 查找COCO格式的标注文件
    for root, _dirs, files in os.walk(dataset_path):
        for file in files:
            if len(preview_items) >= limit:
                break
            if file.endswith('.json'):
                json_path = os.path.join(root, file)
                if _should_skip_file(json_path):
                    continue
                _process_coco_json_file(json_path, preview_items, limit)
        if len(preview_items) >= limit:
            break

    return preview_items


def _should_skip_file(file_path: str, max_size: int = 100 * 1024 * 1024) -> bool:
    """
    检查文件是否应该跳过（大小检查）

    Args:
        file_path: 文件路径
        max_size: 最大文件大小（默认100MB）

    Returns:
        是否应该跳过
    """
    try:
        if os.path.getsize(file_path) > max_size:
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            print(
                f"Skipping large file {os.path.basename(file_path)} ({size_mb:.2f}MB)"
            )
            return True
    except Exception as e:
        print(f"Error checking file size: {e}")
    return False


def _build_alpaca_preview_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建Alpaca预览条目

    Args:
        item: 原始数据项

    Returns:
        预览条目
    """
    return {
        'instruction': item.get('instruction', ''),
        'input': item.get('input', ''),
        'output': item.get('output', ''),
    }


def _process_alpaca_list_items(
    items: List[Dict[str, Any]], preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理Alpaca格式的列表数据

    Args:
        items: 数据列表
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    for item in items[:limit]:
        if len(preview_items) >= limit:
            break
        preview_item = _build_alpaca_preview_item(item)
        preview_items.append(preview_item)


def _process_alpaca_json_file(
    file_path: str, preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理Alpaca格式的JSON文件

    Args:
        file_path: 文件路径
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                _process_alpaca_list_items(data, preview_items, limit)
            elif isinstance(data, dict):
                for _key, value in data.items():
                    if len(preview_items) >= limit:
                        break
                    if isinstance(value, list):
                        _process_alpaca_list_items(value, preview_items, limit)
    except Exception as e:
        print(f"Error processing Alpaca JSON file {os.path.basename(file_path)}: {e}")


def _process_alpaca_jsonl_file(
    file_path: str, preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理Alpaca格式的JSONL文件

    Args:
        file_path: 文件路径
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            line_count = 0
            max_lines = limit * 2  # 读取两倍限制的行数，以防有无效行
            for line in f:
                if line_count >= max_lines or len(preview_items) >= limit:
                    break
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        preview_item = _build_alpaca_preview_item(item)
                        preview_items.append(preview_item)
                    except json.JSONDecodeError:
                        continue
                line_count += 1
    except Exception as e:
        print(f"Error processing Alpaca JSONL file {os.path.basename(file_path)}: {e}")


async def preview_alpaca_dataset(
    dataset_path: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """
    预览Alpaca格式的LLM SFT数据集

    Args:
        dataset_path: 数据集路径
        limit: 预览条目数量

    Returns:
        预览数据列表
    """
    preview_items = []

    # 查找JSON或JSONL文件
    for root, _dirs, files in os.walk(dataset_path):
        for file in files:
            if len(preview_items) >= limit:
                break
            if file.endswith('.json'):
                file_path = os.path.join(root, file)
                if _should_skip_file(file_path):
                    continue
                _process_alpaca_json_file(file_path, preview_items, limit)
            elif file.endswith('.jsonl'):
                file_path = os.path.join(root, file)
                if _should_skip_file(file_path):
                    continue
                _process_alpaca_jsonl_file(file_path, preview_items, limit)
        if len(preview_items) >= limit:
            break

    return preview_items


def _build_llava_preview_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建LLaVA预览条目

    Args:
        item: 原始数据项

    Returns:
        预览条目
    """
    return {
        'id': item.get('id', ''),
        'image': item.get('image', ''),
        'conversations': item.get('conversations', [])[:5],  # 限制对话数量
    }


def _process_llava_list_items(
    items: List[Dict[str, Any]], preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理LLaVA格式的列表数据

    Args:
        items: 数据列表
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    for item in items[:limit]:
        if len(preview_items) >= limit:
            break
        preview_item = _build_llava_preview_item(item)
        preview_items.append(preview_item)


def _process_llava_json_file(
    file_path: str, preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理LLaVA格式的JSON文件

    Args:
        file_path: 文件路径
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                _process_llava_list_items(data, preview_items, limit)
            elif isinstance(data, dict):
                for _key, value in data.items():
                    if len(preview_items) >= limit:
                        break
                    if isinstance(value, list):
                        _process_llava_list_items(value, preview_items, limit)
    except Exception as e:
        print(f"Error processing LLaVA JSON file {os.path.basename(file_path)}: {e}")


def _process_llava_jsonl_file(
    file_path: str, preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理LLaVA格式的JSONL文件

    Args:
        file_path: 文件路径
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            line_count = 0
            max_lines = limit * 2  # 读取两倍限制的行数，以防有无效行
            for line in f:
                if line_count >= max_lines or len(preview_items) >= limit:
                    break
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        preview_item = _build_llava_preview_item(item)
                        preview_items.append(preview_item)
                    except json.JSONDecodeError:
                        continue
                line_count += 1
    except Exception as e:
        print(f"Error processing LLaVA JSONL file {os.path.basename(file_path)}: {e}")


async def preview_llava_dataset(
    dataset_path: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """
    预览LLaVA格式的多模态SFT数据集

    Args:
        dataset_path: 数据集路径
        limit: 预览条目数量

    Returns:
        预览数据列表
    """
    preview_items = []

    # 查找JSON或JSONL文件
    for root, _dirs, files in os.walk(dataset_path):
        for file in files:
            if len(preview_items) >= limit:
                break
            if file.endswith('.json'):
                file_path = os.path.join(root, file)
                if _should_skip_file(file_path):
                    continue
                _process_llava_json_file(file_path, preview_items, limit)
            elif file.endswith('.jsonl'):
                file_path = os.path.join(root, file)
                if _should_skip_file(file_path):
                    continue
                _process_llava_jsonl_file(file_path, preview_items, limit)
        if len(preview_items) >= limit:
            break

    return preview_items


def _build_rlhf_preview_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建RLHF预览条目

    Args:
        item: 原始数据项

    Returns:
        预览条目
    """
    return {
        'id': item.get('id', ''),
        'prompt': item.get('prompt', '')[:1000],  # 限制文本长度
        'chosen': item.get('chosen', '')[:1000],  # 限制文本长度
        'rejected': item.get('rejected', '')[:1000],  # 限制文本长度
    }


def _process_rlhf_list_items(
    items: List[Dict[str, Any]], preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理RLHF格式的列表数据

    Args:
        items: 数据列表
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    for item in items[:limit]:
        if len(preview_items) >= limit:
            break
        preview_item = _build_rlhf_preview_item(item)
        preview_items.append(preview_item)


def _process_rlhf_json_file(
    file_path: str, preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理RLHF格式的JSON文件

    Args:
        file_path: 文件路径
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                _process_rlhf_list_items(data, preview_items, limit)
            elif isinstance(data, dict):
                for _key, value in data.items():
                    if len(preview_items) >= limit:
                        break
                    if isinstance(value, list):
                        _process_rlhf_list_items(value, preview_items, limit)
    except Exception as e:
        print(f"Error processing RLHF JSON file {os.path.basename(file_path)}: {e}")


def _process_rlhf_jsonl_file(
    file_path: str, preview_items: List[Dict[str, Any]], limit: int
) -> None:
    """
    处理RLHF格式的JSONL文件

    Args:
        file_path: 文件路径
        preview_items: 预览条目列表
        limit: 预览条目数量限制
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            line_count = 0
            max_lines = limit * 2  # 读取两倍限制的行数，以防有无效行
            for line in f:
                if line_count >= max_lines or len(preview_items) >= limit:
                    break
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        preview_item = _build_rlhf_preview_item(item)
                        preview_items.append(preview_item)
                    except json.JSONDecodeError:
                        continue
                line_count += 1
    except Exception as e:
        print(f"Error processing RLHF JSONL file {os.path.basename(file_path)}: {e}")


async def preview_rlhf_dataset(
    dataset_path: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """
    预览RLHF/DPO Preference格式的数据集

    Args:
        dataset_path: 数据集路径
        limit: 预览条目数量

    Returns:
        预览数据列表
    """
    preview_items = []

    # 查找JSON或JSONL文件
    for root, _dirs, files in os.walk(dataset_path):
        for file in files:
            if len(preview_items) >= limit:
                break
            if file.endswith('.json'):
                file_path = os.path.join(root, file)
                if _should_skip_file(file_path):
                    continue
                _process_rlhf_json_file(file_path, preview_items, limit)
            elif file.endswith('.jsonl'):
                file_path = os.path.join(root, file)
                if _should_skip_file(file_path):
                    continue
                _process_rlhf_jsonl_file(file_path, preview_items, limit)
        if len(preview_items) >= limit:
            break

    return preview_items


@router.delete("/{dataset_id}/versions/{version_id}")
async def delete_dataset_version(
    session: SessionDep,
    dataset_id: int,
    version_id: int,
):
    """
    删除数据集版本

    Args:
        session: 数据库会话
        dataset_id: 数据集ID
        version_id: 版本ID
    """
    # 检查数据集是否存在
    dataset = await Dataset.one_by_id(session, dataset_id)
    if not dataset:
        raise NotFoundException(message="Dataset not found")

    # 检查版本是否存在且属于该数据集
    version = await DatasetVersion.one_by_id(session, version_id)
    if not version or version.dataset_id != dataset_id:
        raise NotFoundException(message="Dataset version not found")

    try:
        await DatasetVersion.delete(session, version_id)
    except Exception as e:
        raise InternalServerErrorException(
            message=f"Failed to delete dataset version: {e}"
        )


@router.get("/{dataset_id}/versions/{version_id}/preview")
async def preview_dataset_version(
    session: SessionDep,
    dataset_id: int,
    version_id: int,
    dataset_type: str = Query(..., description="数据集类型: coco, alpaca, llava, rlhf"),
    limit: int = Query(10, description="预览条目数量"),
):
    """
    预览数据集版本内容

    Args:
        session: 数据库会话
        dataset_id: 数据集ID
        version_id: 版本ID
        dataset_type: 数据集类型 (coco, alpaca, llava, rlhf)
        limit: 预览条目数量

    Returns:
        预览数据列表
    """
    # 检查数据集是否存在
    dataset = await Dataset.one_by_id(session, dataset_id)
    if not dataset:
        raise NotFoundException(message="Dataset not found")

    # 检查版本是否存在且属于该数据集
    version = await DatasetVersion.one_by_id(session, version_id)
    if not version or version.dataset_id != dataset_id:
        raise NotFoundException(message="Dataset version not found")

    # 检查数据集路径是否存在
    dataset_path = version.path
    if not os.path.exists(dataset_path):
        raise NotFoundException(message="Dataset path not found")

    try:
        # 根据数据集类型调用对应的预览函数
        if dataset_type == "coco":
            preview_data = await preview_coco_dataset(dataset_path, limit)
        elif dataset_type == "alpaca":
            preview_data = await preview_alpaca_dataset(dataset_path, limit)
        elif dataset_type == "llava":
            preview_data = await preview_llava_dataset(dataset_path, limit)
        elif dataset_type == "rlhf":
            preview_data = await preview_rlhf_dataset(dataset_path, limit)
        else:
            raise NotFoundException(message=f"Unsupported dataset type: {dataset_type}")

        return {
            "dataset_id": dataset_id,
            "version_id": version_id,
            "dataset_type": dataset_type,
            "preview_count": len(preview_data),
            "preview_data": preview_data,
        }
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to preview dataset: {e}")
