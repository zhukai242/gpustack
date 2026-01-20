from typing import Optional, List
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from gpustack.api.exceptions import NotFoundException, BadRequestException
from gpustack.server.deps import SessionDep, get_admin_user, CurrentUserDep
from gpustack.schemas.user_groups import (
    UserGroup,
    UserGroupCreate,
    UserGroupUpdate,
    UserGroupPublic,
    UserGroupDetail,
    UserGroupListParams,
    UserGroupResource,
    UserGroupResourceCreate,
    UserGroupMember,
    UserGroupMemberCreate,
    UserGroupsPublic,
)
from gpustack.schemas.tenants import TenantResource
from gpustack.schemas.users import User
from gpustack.schemas.load import GPULoad
from gpustack.schemas.gpu_devices import GPUDevice
from gpustack.schemas.workers import Worker
from sqlmodel import select, func, or_


class GPUCardInfo(BaseModel):
    """GPU card information model."""

    card_id: str
    card_type: str
    node_name: str
    user_group: Optional[str] = None
    current_usage: float = 0.0
    current_temperature: Optional[float] = None
    status: str


router = APIRouter()


# ============ User Group Routes ============


@router.post(
    "",
    response_model=UserGroupPublic,
    status_code=201,
    dependencies=[Depends(get_admin_user)],
)
async def create_user_group(group_create: UserGroupCreate, session: SessionDep):
    """
    Create a new user group with optional members and resources.
    """
    # Verify tenant exists
    from gpustack.schemas.tenants import Tenant

    tenant = await Tenant.one_by_id(session, group_create.tenant_id)
    if not tenant or tenant.deleted_at:
        raise NotFoundException(f"Tenant with ID {group_create.tenant_id} not found")

    # Create user group
    user_group = UserGroup.model_validate(
        group_create, update={"member_ids": [], "resource_ids": []}
    )
    session.add(user_group)
    await session.flush()

    # Add members if provided
    if group_create.member_ids:
        for user_id in group_create.member_ids:
            member = UserGroupMemberCreate(user_group_id=user_group.id, user_id=user_id)
            session.add(member)

    # Add resources if provided
    if group_create.resource_ids:
        from gpustack.schemas.tenants import TenantResource

        for resource_id in group_create.resource_ids:
            # Get tenant resource details to get worker_id and gpu_id
            tenant_resource = await TenantResource.one_by_id(session, resource_id)
            if not tenant_resource or tenant_resource.deleted_at:
                raise NotFoundException(
                    f"Tenant resource with ID {resource_id} not found"
                )

            # Create user group resource with worker_id and gpu_id
            resource = UserGroupResourceCreate(
                user_group_id=user_group.id,
                tenant_resource_id=resource_id,
                worker_id=tenant_resource.worker_id,
                gpu_id=tenant_resource.gpu_id,
            )
            session.add(resource)

    await session.commit()
    await session.refresh(user_group)

    # Count members and resources for response
    member_count = len(group_create.member_ids) if group_create.member_ids else 0
    resource_count = len(group_create.resource_ids) if group_create.resource_ids else 0

    return UserGroupPublic(
        **user_group.model_dump(),
        member_count=member_count,
        resource_count=resource_count,
    )


@router.get("", response_model=UserGroupsPublic)
async def list_user_groups(
    session: SessionDep,
    params: UserGroupListParams = Depends(),
    tenant_id: Optional[int] = None,
    status: Optional[str] = None,
    group_name: Optional[str] = None,
):
    """
    List user groups with optional filtering.
    """
    fields = {}
    if tenant_id:
        fields["tenant_id"] = tenant_id
    if status:
        fields["status"] = status
    if group_name:
        # Handle partial name search
        pass

    # Get paginated user groups
    user_groups = await UserGroup.paginated_by_query(
        session=session,
        fields=fields,
        page=params.page,
        per_page=params.perPage,
        order_by=params.order_by,
    )

    # Count members for each group
    for group in user_groups.items:
        # Get members count
        member_count = await session.exec(
            select(func.count(UserGroupMember.id))
            .where(UserGroupMember.user_group_id == group.id)
            .where(UserGroupMember.deleted_at.is_(None))
        )
        group.member_count = member_count.scalar() or 0

        # Get resources with details
        resources = await session.exec(
            select(TenantResource)
            .join(
                UserGroupResource,
                UserGroupResource.tenant_resource_id == TenantResource.id,
            )
            .where(UserGroupResource.user_group_id == group.id)
            .where(UserGroupResource.deleted_at.is_(None))
            .where(TenantResource.deleted_at.is_(None))
        )
        resources = resources.all()
        group.resource_count = len(resources)

        # Calculate node count
        group.node_count = len(set(r.worker_id for r in resources))

        # Calculate GPU type counts
        gpu_type_counts = {}
        gpu_ids = [r.gpu_id for r in resources if r.gpu_id]

        if gpu_ids:
            # Get GPU device details to get arch_family
            gpu_devices = await session.exec(
                select(GPUDevice)
                .where(GPUDevice.id.in_(gpu_ids))
                .where(GPUDevice.deleted_at.is_(None))
            )
            gpu_devices = gpu_devices.all()

            for gpu_device in gpu_devices:
                arch_family = gpu_device.arch_family or "unknown"
                gpu_type_counts[arch_family] = gpu_type_counts.get(arch_family, 0) + 1

        group.gpu_type_counts = gpu_type_counts

        # Calculate average GPU and VRAM utilization
        if gpu_ids:
            # Get latest GPU loads for each GPU
            latest_loads_query = select(
                GPULoad.gpu_id, func.max(GPULoad.timestamp).label('latest_timestamp')
            ).where(GPULoad.gpu_id.in_(gpu_ids))
            latest_loads_query = latest_loads_query.group_by(GPULoad.gpu_id)
            latest_loads = await session.exec(latest_loads_query)
            latest_loads = latest_loads.all()

            if latest_loads:
                # Create a list of conditions for getting the latest load data
                conditions = []
                for ll in latest_loads:
                    conditions.append(
                        (GPULoad.gpu_id == ll.gpu_id)
                        & (GPULoad.timestamp == ll.latest_timestamp)
                    )

                from sqlalchemy import or_

                load_data = await session.exec(select(GPULoad).where(or_(*conditions)))
                load_data = load_data.all()

                if load_data:
                    avg_gpu = sum(
                        load.gpu_utilization or 0 for load in load_data
                    ) / len(load_data)
                    avg_vram = sum(
                        load.vram_utilization or 0 for load in load_data
                    ) / len(load_data)
                    group.gpu_utilization = round(avg_gpu, 2)
                    group.vram_utilization = round(avg_vram, 2)
                else:
                    group.gpu_utilization = 0.0
                    group.vram_utilization = 0.0
            else:
                group.gpu_utilization = 0.0
                group.vram_utilization = 0.0
        else:
            group.gpu_utilization = 0.0
            group.vram_utilization = 0.0

    return user_groups


@router.get("/{group_id}", response_model=UserGroupDetail)
async def get_user_group(
    group_id: int,
    session: SessionDep,
    time_dimension: Optional[str] = "week",  # today, week, month
):
    """
    Get user group details with resource usage trend.
    """
    # Get user group
    user_group = await UserGroup.one_by_id(session, group_id)
    if not user_group or user_group.deleted_at:
        raise NotFoundException(f"User group with ID {group_id} not found")

    # Get members
    members = await session.exec(
        select(User)
        .join(UserGroupMember, User.id == UserGroupMember.user_id)
        .where(UserGroupMember.user_group_id == group_id)
    )
    member_details = members.all()

    # Get resources
    resources = await session.exec(
        select(TenantResource)
        .join(
            UserGroupResource, TenantResource.id == UserGroupResource.tenant_resource_id
        )
        .where(UserGroupResource.user_group_id == group_id)
    )
    resource_details = resources.all()

    # Get GPU IDs for this group
    gpu_ids = [r.gpu_id for r in resource_details if r.gpu_id]

    # Get historical GPU load data
    now = datetime.now(timezone.utc)
    if time_dimension == "today":
        start_time = now - timedelta(days=1)
    elif time_dimension == "week":
        start_time = now - timedelta(days=7)
    elif time_dimension == "month":
        start_time = now - timedelta(days=30)
    else:
        start_time = now - timedelta(days=7)

    gpu_history = []
    vram_history = []

    if gpu_ids:
        # Get average GPU/VRAM utilization per hour
        stmt = (
            select(
                func.date_trunc('hour', GPULoad.timestamp).label('hour'),
                func.avg(GPULoad.gpu_utilization).label('avg_gpu'),
                func.avg(GPULoad.vram_utilization).label('avg_vram'),
            )
            .where(GPULoad.gpu_id.in_(gpu_ids))
            .where(GPULoad.timestamp >= start_time)
            .group_by(func.date_trunc('hour', GPULoad.timestamp))
            .order_by(func.date_trunc('hour', GPULoad.timestamp))
        )

        results = await session.exec(stmt)

        # Create time series data
        for result in results:
            from gpustack.schemas.dashboard import TimeSeriesData

            gpu_history.append(
                TimeSeriesData(
                    timestamp=int(result.hour.timestamp()), value=result.avg_gpu or 0.0
                )
            )
            vram_history.append(
                TimeSeriesData(
                    timestamp=int(result.hour.timestamp()), value=result.avg_vram or 0.0
                )
            )

    return UserGroupDetail(
        **user_group.model_dump(),
        member_count=len(member_details),
        resource_count=len(resource_details),
        member_details=member_details,
        resource_details=resource_details,
        gpu_utilization_trend=gpu_history,
        vram_utilization_trend=vram_history,
    )


@router.put(
    "/{group_id}",
    response_model=UserGroupPublic,
    dependencies=[Depends(get_admin_user)],
)
async def update_user_group(
    group_id: int, group_update: UserGroupUpdate, session: SessionDep
):
    """
    Update a user group.
    """
    # Get user group
    user_group = await UserGroup.one_by_id(session, group_id)
    if not user_group or user_group.deleted_at:
        raise NotFoundException(f"User group with ID {group_id} not found")

    # Update user group
    update_data = group_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user_group, field, value)

    session.add(user_group)
    await session.commit()
    await session.refresh(user_group)

    # Count members and resources for response
    member_count = await session.exec(
        select(func.count(UserGroupMember.id)).where(
            UserGroupMember.user_group_id == group_id
        )
    )
    resource_count = await session.exec(
        select(func.count(UserGroupResource.id)).where(
            UserGroupResource.user_group_id == group_id
        )
    )

    return UserGroupPublic(
        **user_group.model_dump(),
        member_count=member_count.scalar() or 0,
        resource_count=resource_count.scalar() or 0,
    )


@router.delete("/{group_id}", status_code=204, dependencies=[Depends(get_admin_user)])
async def delete_user_group(group_id: int, session: SessionDep):
    """
    Delete a user group.
    """
    # Get user group
    user_group = await UserGroup.one_by_id(session, group_id)
    if not user_group or user_group.deleted_at:
        raise NotFoundException(f"User group with ID {group_id} not found")

    # Soft delete user group
    from gpustack.mixins import soft_delete

    await soft_delete(session, user_group)
    await session.commit()

    return {}


# ============ User Group Member Routes ============


@router.post(
    "/{group_id}/members", status_code=201, dependencies=[Depends(get_admin_user)]
)
async def add_group_member(group_id: int, user_id: int, session: SessionDep):
    """
    Add a member to a user group.
    """
    # Verify user group exists
    user_group = await UserGroup.one_by_id(session, group_id)
    if not user_group or user_group.deleted_at:
        raise NotFoundException(f"User group with ID {group_id} not found")

    # Verify user exists
    user = await User.one_by_id(session, user_id)
    if not user or user.deleted_at:
        raise NotFoundException(f"User with ID {user_id} not found")

    # Check if already member
    existing_member = await session.exec(
        select(UserGroupMember)
        .where(UserGroupMember.user_group_id == group_id)
        .where(UserGroupMember.user_id == user_id)
    )
    if existing_member.first():
        raise BadRequestException(
            f"User {user_id} is already a member of group {group_id}"
        )

    # Add member
    member = UserGroupMemberCreate(user_group_id=group_id, user_id=user_id)
    session.add(member)
    await session.commit()

    return {"message": "Member added successfully"}


@router.delete(
    "/{group_id}/members/{user_id}",
    status_code=204,
    dependencies=[Depends(get_admin_user)],
)
async def remove_group_member(group_id: int, user_id: int, session: SessionDep):
    """
    Remove a member from a user group.
    """
    # Verify member exists
    member = await session.exec(
        select(UserGroupMember)
        .where(UserGroupMember.user_group_id == group_id)
        .where(UserGroupMember.user_id == user_id)
    )
    member = member.first()
    if not member or member.deleted_at:
        raise NotFoundException("Member not found in group")

    # Remove member
    from gpustack.mixins import soft_delete

    await soft_delete(session, member)
    await session.commit()

    return {"message": "Member removed successfully"}


# ============ User Group Resource Routes ============


@router.post(
    "/{group_id}/resources", status_code=201, dependencies=[Depends(get_admin_user)]
)
async def add_group_resource(
    group_id: int, tenant_resource_id: int, session: SessionDep
):
    """
    Add a resource to a user group.
    """
    # Verify user group exists
    user_group = await UserGroup.one_by_id(session, group_id)
    if not user_group or user_group.deleted_at:
        raise NotFoundException(f"User group with ID {group_id} not found")

    # Verify resource exists
    resource = await TenantResource.one_by_id(session, tenant_resource_id)
    if not resource or resource.deleted_at:
        raise NotFoundException(f"Resource with ID {tenant_resource_id} not found")

    # Check if already added
    existing_resource = await session.exec(
        select(UserGroupResource)
        .where(UserGroupResource.user_group_id == group_id)
        .where(UserGroupResource.tenant_resource_id == tenant_resource_id)
    )
    if existing_resource.first():
        raise BadRequestException(
            f"Resource {tenant_resource_id} is already in group {group_id}"
        )

    # Add resource
    group_resource = UserGroupResourceCreate(
        user_group_id=group_id,
        tenant_resource_id=tenant_resource_id,
        worker_id=resource.worker_id,
        gpu_id=resource.gpu_id,
    )
    session.add(group_resource)
    await session.commit()

    return {"message": "Resource added successfully"}


@router.delete(
    "/{group_id}/resources/{tenant_resource_id}",
    status_code=204,
    dependencies=[Depends(get_admin_user)],
)
async def remove_group_resource(
    group_id: int, tenant_resource_id: int, session: SessionDep
):
    """
    Remove a resource from a user group.
    """
    # Verify resource exists in group
    group_resource = await session.exec(
        select(UserGroupResource)
        .where(UserGroupResource.user_group_id == group_id)
        .where(UserGroupResource.tenant_resource_id == tenant_resource_id)
    )
    group_resource = group_resource.first()
    if not group_resource or group_resource.deleted_at:
        raise NotFoundException("Resource not found in group")

    # Remove resource
    from gpustack.mixins import soft_delete

    await soft_delete(session, group_resource)
    await session.commit()

    return {"message": "Resource removed successfully"}


# ============ User Group Stats Routes ============


@router.get("/stats/summary")
async def get_user_group_stats(session: SessionDep, tenant_id: Optional[int] = None):
    """
    Get user group statistics.
    """
    # Base query filters
    filters = {}
    if tenant_id:
        filters["tenant_id"] = tenant_id

    # Get total user groups
    total_groups = await session.exec(
        select(func.count(UserGroup.id))
        .where(UserGroup.deleted_at.is_(None))
        .where(UserGroup.tenant_id == tenant_id if tenant_id else True)
    )
    total_groups = total_groups.scalar() or 0

    # Get total members
    total_members = await session.exec(
        select(func.count(func.distinct(UserGroupMember.user_id)))
        .join(UserGroup, UserGroup.id == UserGroupMember.user_group_id)
        .where(UserGroupMember.deleted_at.is_(None))
        .where(UserGroup.deleted_at.is_(None))
        .where(UserGroup.tenant_id == tenant_id if tenant_id else True)
    )
    total_members = total_members.scalar() or 0

    # Get total nodes and GPUs for the tenant
    from gpustack.schemas.tenants import TenantResource

    total_nodes = await session.exec(
        select(func.count(func.distinct(TenantResource.worker_id)))
        .where(TenantResource.deleted_at.is_(None))
        .where(TenantResource.tenant_id == tenant_id if tenant_id else True)
    )
    total_nodes = total_nodes.scalar() or 0

    total_gpus = await session.exec(
        select(func.count(TenantResource.id))
        .where(TenantResource.deleted_at.is_(None))
        .where(TenantResource.tenant_id == tenant_id if tenant_id else True)
    )
    total_gpus = total_gpus.scalar() or 0

    # Get group resource usage
    group_usage = []

    # Get all user groups
    groups = await session.exec(
        select(UserGroup)
        .where(UserGroup.deleted_at.is_(None))
        .where(UserGroup.tenant_id == tenant_id if tenant_id else True)
    )
    groups = groups.all()

    for group in groups:
        # Count group members
        member_count = await session.exec(
            select(func.count(UserGroupMember.id))
            .where(UserGroupMember.user_group_id == group.id)
            .where(UserGroupMember.deleted_at.is_(None))
        )
        member_count = member_count.scalar() or 0

        # Count group resources
        resources = await session.exec(
            select(TenantResource)
            .join(
                UserGroupResource,
                UserGroupResource.tenant_resource_id == TenantResource.id,
            )
            .where(UserGroupResource.user_group_id == group.id)
            .where(UserGroupResource.deleted_at.is_(None))
            .where(TenantResource.deleted_at.is_(None))
        )
        resources = resources.all()
        gpu_count = len(resources)

        # Count unique nodes in group
        node_count = len(set(r.worker_id for r in resources))

        # Calculate average GPU and VRAM utilization
        gpu_ids = [r.gpu_id for r in resources if r.gpu_id]
        avg_gpu_util = 0.0
        avg_vram_util = 0.0

        if gpu_ids:
            # Get latest GPU loads
            latest_loads = await session.exec(
                select(
                    GPULoad.gpu_id,
                    func.max(GPULoad.timestamp).label('latest_timestamp'),
                )
                .where(GPULoad.gpu_id.in_(gpu_ids))
                .group_by(GPULoad.gpu_id)
            )
            latest_loads = latest_loads.all()

            if latest_loads:
                # Get actual load data
                from sqlalchemy import or_

                conditions = [
                    (GPULoad.gpu_id == ll.gpu_id)
                    & (GPULoad.timestamp == ll.latest_timestamp)
                    for ll in latest_loads
                ]
                load_data = await session.exec(select(GPULoad).where(or_(*conditions)))
                load_data = load_data.all()

                if load_data:
                    avg_gpu_util = sum(
                        load.gpu_utilization or 0 for load in load_data
                    ) / len(load_data)
                    avg_vram_util = sum(
                        load.vram_utilization or 0 for load in load_data
                    ) / len(load_data)

        group_usage.append(
            {
                "group_id": group.id,
                "group_name": group.name,
                "gpu_count": gpu_count,
                "gpu_utilization": avg_gpu_util,
                "vram_utilization": avg_vram_util,
                "node_count": node_count,
                "member_count": member_count,
            }
        )

    return {
        "total_user_groups": total_groups,
        "total_members": total_members,
        "total_nodes": total_nodes,
        "total_gpus": total_gpus,
        "group_resource_usage": group_usage,
    }


@router.get("/{group_id}/resources/trend")
async def get_group_resource_trend(
    group_id: int,
    session: SessionDep,
    time_dimension: str = Query(
        "week", description="Time dimension: today, week, month"
    ),
):
    """
    Get resource usage trend for a user group.
    """
    # Verify user group exists
    user_group = await UserGroup.one_by_id(session, group_id)
    if not user_group or user_group.deleted_at:
        raise NotFoundException(f"User group with ID {group_id} not found")

    # Get resources for this group
    resources = await session.exec(
        select(TenantResource)
        .join(
            UserGroupResource, UserGroupResource.tenant_resource_id == TenantResource.id
        )
        .where(UserGroupResource.user_group_id == group_id)
        .where(UserGroupResource.deleted_at.is_(None))
        .where(TenantResource.deleted_at.is_(None))
    )
    resources = resources.all()

    # Get GPU IDs for this group
    gpu_ids = [r.gpu_id for r in resources if r.gpu_id]

    # Calculate time range
    now = datetime.now(timezone.utc)
    if time_dimension == "today":
        start_time = now - timedelta(days=1)
    elif time_dimension == "week":
        start_time = now - timedelta(days=7)
    elif time_dimension == "month":
        start_time = now - timedelta(days=30)
    else:
        start_time = now - timedelta(days=7)

    # Get historical GPU load data
    from gpustack.schemas.dashboard import TimeSeriesData

    gpu_history = []
    vram_history = []

    if gpu_ids:
        # Get average GPU/VRAM utilization per hour
        stmt = (
            select(
                func.date_trunc('hour', GPULoad.timestamp).label('hour'),
                func.avg(GPULoad.gpu_utilization).label('avg_gpu'),
                func.avg(GPULoad.vram_utilization).label('avg_vram'),
            )
            .where(GPULoad.gpu_id.in_(gpu_ids))
            .where(GPULoad.timestamp >= start_time)
            .group_by(func.date_trunc('hour', GPULoad.timestamp))
            .order_by(func.date_trunc('hour', GPULoad.timestamp))
        )

        results = await session.exec(stmt)

        # Create time series data
        for result in results:
            gpu_history.append(
                TimeSeriesData(
                    timestamp=int(result.hour.timestamp()), value=result.avg_gpu or 0.0
                )
            )
            vram_history.append(
                TimeSeriesData(
                    timestamp=int(result.hour.timestamp()), value=result.avg_vram or 0.0
                )
            )

    return {
        "group_id": group_id,
        "time_dimension": time_dimension,
        "gpu_utilization_trend": gpu_history,
        "vram_utilization_trend": vram_history,
        "gpu_count": len(resources),
    }


@router.get("/tenant/gpu-cards", response_model=List[GPUCardInfo])
async def get_tenant_gpu_cards(
    session: SessionDep,
    current_user: CurrentUserDep,
    tenant_id: Optional[int] = Query(None, description="Tenant ID"),
    card_name: Optional[str] = Query(None, description="Fuzzy search by card name"),
    device_name: Optional[str] = Query(None, description="Fuzzy search by device name"),
):
    """
    Get all GPU cards under the current tenant with detailed information.
    Supports fuzzy search by card name and device name.
    """
    # Use current user's tenant ID if not provided
    if not tenant_id:
        tenant_id = current_user.tenant_id

    # Base query for GPU devices with tenant resources
    stmt = (
        select(
            GPUDevice.id.label('card_id'),
            GPUDevice.arch_family.label('card_type'),
            Worker.name.label('node_name'),
            UserGroup.name.label('user_group_name'),
            GPUDevice.temperature.label('current_temperature'),
            Worker.state.label('worker_status'),  # Add worker status
        )
        .join(TenantResource, GPUDevice.id == TenantResource.gpu_id)
        .join(Worker, Worker.id == TenantResource.worker_id)
        .outerjoin(
            UserGroupResource, UserGroupResource.tenant_resource_id == TenantResource.id
        )
        .outerjoin(UserGroup, UserGroup.id == UserGroupResource.user_group_id)
        .where(TenantResource.deleted_at.is_(None))
        .where(GPUDevice.deleted_at.is_(None))
    )

    # Apply tenant_id filter if provided
    if tenant_id is not None:
        stmt = stmt.where(TenantResource.tenant_id == tenant_id)

    # Apply fuzzy search filters
    if card_name:
        stmt = stmt.where(GPUDevice.id.ilike(f"%{card_name}%"))

    if device_name:
        stmt = stmt.where(Worker.name.ilike(f"%{device_name}%"))

    # Execute query to get GPU cards information
    results = await session.exec(stmt)
    gpu_cards = results.all()

    # Get all GPU IDs to fetch latest load data
    gpu_ids = [card[0] for card in gpu_cards]  # card[0] is card_id

    # Get latest GPU load data
    latest_loads = {}
    if gpu_ids:
        latest_load_query = (
            select(
                GPULoad.gpu_id, func.max(GPULoad.timestamp).label('latest_timestamp')
            )
            .where(GPULoad.gpu_id.in_(gpu_ids))
            .group_by(GPULoad.gpu_id)
        )

        latest_load_results = await session.exec(latest_load_query)
        latest_loads_info = latest_load_results.all()

        # Create a dictionary of latest timestamps for each GPU
        latest_timestamps = {ll.gpu_id: ll.latest_timestamp for ll in latest_loads_info}

        # Get actual load data for these timestamps
        if latest_timestamps:
            load_conditions = []
            for gpu_id, timestamp in latest_timestamps.items():
                load_conditions.append(
                    (GPULoad.gpu_id == gpu_id) & (GPULoad.timestamp == timestamp)
                )

            load_query = select(GPULoad.gpu_id, GPULoad.gpu_utilization).where(
                or_(*load_conditions)
            )

            load_results = await session.exec(load_query)
            for load in load_results.all():
                latest_loads[load.gpu_id] = load.gpu_utilization or 0.0

    # Format the response
    response = []
    for card in gpu_cards:
        response.append(
            GPUCardInfo(
                card_id=card[0],  # card_id
                card_type=card[1] or "unknown",  # card_type
                node_name=card[2],  # node_name
                user_group=card[3],  # user_group_name
                current_usage=latest_loads.get(card[0], 0.0),  # Use card_id as key
                current_temperature=card[4],  # current_temperature
                status=card[5],  # Use worker status
            )
        )

    return response
