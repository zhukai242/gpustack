from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from gpustack.server.db import get_session
from gpustack.schemas.licenses import (
    License,
    LicenseCreate,
    LicenseUpdate,
    LicensePublic,
    LicensesPublic,
    LicenseListParams,
    LicenseActivation,
    LicenseActivationCreate,
    LicenseActivationPublic,
    LicenseStatusEnum,
)


router = APIRouter(prefix="/licenses", tags=["licenses"])


@router.post("/", response_model=LicensePublic)
async def create_license(
    license_data: LicenseCreate, session: AsyncSession = Depends(get_session)
):
    """
    Create a new license.
    """
    # Check if license code already exists
    existing_license = await session.exec(
        select(License).where(License.license_code == license_data.license_code)
    )
    if existing_license.first():
        raise HTTPException(
            status_code=400,
            detail=f"License with code '{license_data.license_code}' already exists",
        )

    # Check if license id already exists
    existing_license = await session.exec(
        select(License).where(License.license_id == license_data.license_id)
    )
    if existing_license.first():
        raise HTTPException(
            status_code=400,
            detail=f"License with id '{license_data.license_id}' already exists",
        )

    db_license = License.model_validate(license_data)
    session.add(db_license)
    await session.commit()
    await session.refresh(db_license)
    return db_license


@router.get("/", response_model=LicensesPublic)
async def list_licenses(
    params: LicenseListParams = Depends(LicenseListParams),
    session: AsyncSession = Depends(get_session),
):
    """
    List all licenses with pagination and filtering.
    """
    # Build order by list from params
    order_by = []
    if params.sort_by and params.order:
        order_by = [(params.sort_by, params.order)]

    # Get paginated items using the model's paginated_by_query method
    paginated_result = await License.paginated_by_query(
        session=session, page=params.page, per_page=params.per_page, order_by=order_by
    )

    # Convert to response model
    return LicensesPublic(
        items=[LicensePublic.model_validate(item) for item in paginated_result.items],
        pagination=paginated_result.pagination,
    )


@router.get("/{license_id}", response_model=LicensePublic)
async def get_license(license_id: int, session: AsyncSession = Depends(get_session)):
    """
    Get a license by ID.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")
    return license


@router.put("/{license_id}", response_model=LicensePublic)
async def update_license(
    license_id: int,
    license_update: LicenseUpdate,
    session: AsyncSession = Depends(get_session),
):
    """
    Update a license.
    """
    db_license = await session.get(License, license_id)
    if not db_license:
        raise HTTPException(status_code=404, detail="License not found")

    update_data = license_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_license, field, value)

    session.add(db_license)
    await session.commit()
    await session.refresh(db_license)
    return db_license


@router.delete("/{license_id}")
async def delete_license(license_id: int, session: AsyncSession = Depends(get_session)):
    """
    Delete a license.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    await session.delete(license)
    await session.commit()
    return {"message": "License deleted successfully"}


@router.post("/{license_id}/activate")
async def activate_license(
    license_id: int, session: AsyncSession = Depends(get_session)
):
    """
    Activate a license.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    if license.status == LicenseStatusEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="License is already activated")

    license.status = LicenseStatusEnum.ACTIVE
    license.activation_time = datetime.utcnow()
    session.add(license)
    await session.commit()
    await session.refresh(license)
    return {"message": "License activated successfully", "license": license}


@router.post("/{license_id}/revoke")
async def revoke_license(license_id: int, session: AsyncSession = Depends(get_session)):
    """
    Revoke a license.
    """
    license = await session.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    if license.status == LicenseStatusEnum.REVOKED:
        raise HTTPException(status_code=400, detail="License is already revoked")

    license.status = LicenseStatusEnum.REVOKED
    session.add(license)
    await session.commit()
    await session.refresh(license)

    # Update all activations for this license to revoked
    activations = await session.exec(
        select(LicenseActivation).where(LicenseActivation.license_id == license_id)
    )
    for activation in activations:
        activation.status = LicenseStatusEnum.REVOKED
        session.add(activation)
    await session.commit()

    return {"message": "License revoked successfully", "license": license}


# License Activation Routes


@router.post("/activations", response_model=LicenseActivationPublic)
async def create_license_activation(
    activation_data: LicenseActivationCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    Create a new license activation.
    """
    # Find the license by license code
    license = await session.exec(
        select(License).where(License.license_code == activation_data.license_code)
    )
    license = license.first()

    if not license:
        raise HTTPException(status_code=404, detail="License not found")

    if license.status != LicenseStatusEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="License is not active")

    # Check if GPU SN is already activated
    existing_activation = await session.exec(
        select(LicenseActivation).where(
            LicenseActivation.gpu_sn == activation_data.gpu_sn
        )
    )
    if existing_activation.first():
        raise HTTPException(
            status_code=400,
            detail=f"GPU with SN '{activation_data.gpu_sn}' is already activated",
        )

    # Check if max GPUs limit is reached
    activation_count = await session.exec(
        select(func.count(LicenseActivation.id)).where(
            LicenseActivation.license_id == license.id
        )
    )
    if activation_count.first() >= license.max_gpus and license.max_gpus > 0:
        raise HTTPException(
            status_code=400,
            detail=f"License GPU limit reached. Maximum {license.max_gpus} GPUs allowed",
        )

    # Create activation
    activation = LicenseActivation.model_validate(activation_data)
    activation.license_id = license.id
    activation.expiration_time = license.expiration_time
    session.add(activation)
    await session.commit()
    await session.refresh(activation)
    return activation


@router.get("/activations", response_model=List[LicenseActivationPublic])
async def list_license_activations(
    license_id: Optional[int] = None,
    worker_id: Optional[int] = None,
    gpu_sn: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    List license activations with filtering.
    """
    query = select(LicenseActivation)

    if license_id:
        query = query.where(LicenseActivation.license_id == license_id)
    if worker_id:
        query = query.where(LicenseActivation.worker_id == worker_id)
    if gpu_sn:
        query = query.where(LicenseActivation.gpu_sn == gpu_sn)

    result = await session.exec(query)
    return result.all()


@router.get("/activations/{activation_id}", response_model=LicenseActivationPublic)
async def get_license_activation(
    activation_id: int, session: AsyncSession = Depends(get_session)
):
    """
    Get a license activation by ID.
    """
    activation = await session.get(LicenseActivation, activation_id)
    if not activation:
        raise HTTPException(status_code=404, detail="License activation not found")
    return activation


@router.delete("/activations/{activation_id}")
async def delete_license_activation(
    activation_id: int, session: AsyncSession = Depends(get_session)
):
    """
    Delete a license activation.
    """
    activation = await session.get(LicenseActivation, activation_id)
    if not activation:
        raise HTTPException(status_code=404, detail="License activation not found")

    await session.delete(activation)
    await session.commit()
    return {"message": "License activation deleted successfully"}
