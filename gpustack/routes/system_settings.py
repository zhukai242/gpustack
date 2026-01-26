from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from gpustack.server.db import get_session
from gpustack.schemas.system_settings import (
    SystemSetting,
    SystemSettingCreate,
    SystemSettingUpdate,
    SystemSettingPublic,
    SystemSettingsPublic,
    SystemSettingListParams,
    SettingCategoryEnum,
)

router = APIRouter(prefix="/system-settings", tags=["system-settings"])


@router.post("/", response_model=SystemSettingPublic)
async def create_system_setting(
    setting: SystemSettingCreate, session: AsyncSession = Depends(get_session)
):
    """
    Create a new system setting.
    """
    # Check if the setting key already exists
    existing_setting = await session.exec(
        select(SystemSetting).where(SystemSetting.key == setting.key)
    )
    if existing_setting.first():
        raise HTTPException(
            status_code=400, detail=f"Setting with key '{setting.key}' already exists"
        )

    db_setting = SystemSetting.model_validate(setting)
    session.add(db_setting)
    await session.commit()
    await session.refresh(db_setting)
    return db_setting


@router.get("/", response_model=SystemSettingsPublic)
async def list_system_settings(
    params: SystemSettingListParams = Depends(SystemSettingListParams),
    category: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    List all system settings with pagination and filtering.
    """
    from gpustack.schemas.system_settings import SettingCategoryEnum, SettingTypeEnum

    # Build filters
    filters = {}

    # Extract filters from params
    if params.type is not None:
        # 确保type值是正确的枚举成员
        if isinstance(params.type, SettingTypeEnum):
            filters["type"] = params.type
        else:
            # 如果是字符串，转换为枚举成员
            filters["type"] = SettingTypeEnum._missing_(params.type)
    if params.key is not None:
        filters["key"] = params.key
    if params.is_required is not None:
        filters["is_required"] = params.is_required
    if params.is_editable is not None:
        filters["is_editable"] = params.is_editable

    if category:
        # 转换category参数为枚举类型
        try:
            filters["category"] = SettingCategoryEnum(category)
        except ValueError:
            filters["category"] = SettingCategoryEnum._missing_(category)

    # Get paginated items using the model's paginated_by_query method
    paginated_result = await SystemSetting.paginated_by_query(
        session=session,
        fields=filters,
        page=params.page,
        per_page=params.perPage,
        order_by=params.order_by,
    )

    # Convert to response model
    return SystemSettingsPublic(
        items=[
            SystemSettingPublic.model_validate(item) for item in paginated_result.items
        ],
        pagination=paginated_result.pagination,
    )


@router.get("/categories", response_model=List[str])
async def get_setting_categories():
    """
    Get all available setting categories.
    """
    return [category.value for category in SettingCategoryEnum]


@router.get("/categories/keys", response_model=List[str])
async def get_setting_category_keys(
    category: Optional[str] = None, session: AsyncSession = Depends(get_session)
):
    """
    Get all unique setting keys for a specific category.
    """
    query = select(func.distinct(SystemSetting.key))
    if category:
        query = query.where(SystemSetting.category == category)
    result = await session.exec(query)
    return result.all()


@router.get("/{setting_id}", response_model=SystemSettingPublic)
async def get_system_setting(
    setting_id: int, session: AsyncSession = Depends(get_session)
):
    """
    Get a system setting by ID.
    """
    setting = await session.get(SystemSetting, setting_id)
    if not setting:
        raise HTTPException(status_code=404, detail="System setting not found")
    return setting


@router.get("/key/{setting_key}", response_model=SystemSettingPublic)
async def get_system_setting_by_key(
    setting_key: str, session: AsyncSession = Depends(get_session)
):
    """
    Get a system setting by key.
    """
    setting = await session.exec(
        select(SystemSetting).where(SystemSetting.key == setting_key)
    )
    setting = setting.first()
    if not setting:
        raise HTTPException(
            status_code=404, detail=f"System setting with key '{setting_key}' not found"
        )
    return setting


@router.put("/{setting_id}", response_model=SystemSettingPublic)
async def update_system_setting(
    setting_id: int,
    setting_update: SystemSettingUpdate,
    session: AsyncSession = Depends(get_session),
):
    """
    Update a system setting.
    """
    db_setting = await session.get(SystemSetting, setting_id)
    if not db_setting:
        raise HTTPException(status_code=404, detail="System setting not found")

    # Check if the setting is editable
    if not db_setting.is_editable:
        raise HTTPException(status_code=400, detail="This setting is not editable")

    update_data = setting_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_setting, field, value)

    session.add(db_setting)
    await session.commit()
    await session.refresh(db_setting)
    return db_setting


@router.delete("/{setting_id}")
async def delete_system_setting(
    setting_id: int, session: AsyncSession = Depends(get_session)
):
    """
    Delete a system setting.
    """
    setting = await session.get(SystemSetting, setting_id)
    if not setting:
        raise HTTPException(status_code=404, detail="System setting not found")

    # Check if the setting is editable
    if not setting.is_editable:
        raise HTTPException(status_code=400, detail="This setting is not editable")

    await session.delete(setting)
    await session.commit()
    return {"message": "System setting deleted successfully"}
