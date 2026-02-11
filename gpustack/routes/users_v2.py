from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from gpustack.api.exceptions import (
    AlreadyExistsException,
    InternalServerErrorException,
    NotFoundException,
    ConflictException,
)
from gpustack.security import get_secret_hash
from gpustack.server.deps import CurrentUserDep, SessionDep
from gpustack.schemas.users import (
    User,
    UserActivationUpdate,
    UserCreate,
    UserListParams,
    UserUpdate,
    UserPublic,
    UserPublicWithGroups,
    UsersPublicWithGroups,
    UserSelfUpdate,
)
from gpustack.schemas.user_groups import UserGroup, UserGroupMember
from sqlmodel import select
from gpustack.server.services import UserService, delete_cache_by_key

router = APIRouter()


@router.get("", response_model=UsersPublicWithGroups)
async def get_users(
    session: SessionDep,
    current_user: CurrentUserDep,
    params: UserListParams = Depends(),
    search: str = None,
):
    fuzzy_fields = {}
    if search:
        fuzzy_fields = {"username": search, "full_name": search}

    # Only show users in the same tenant as current user
    fields = {
        "deleted_at": None,
        "is_system": False,
        "tenant_id": current_user.tenant_id,
    }

    if params.watch:
        return StreamingResponse(
            User.streaming(session=session, fuzzy_fields=fuzzy_fields, fields=fields),
            media_type="text/event-stream",
        )

    # Get paginated users
    result = await User.paginated_by_query(
        session=session,
        fuzzy_fields=fuzzy_fields,
        page=params.page,
        per_page=params.perPage,
        fields=fields,
        order_by=params.order_by,
    )

    # Convert User objects to UserPublicWithGroups models and add user group information
    user_public_list = []
    for user in result.items:
        # Create UserPublicWithGroups model
        user_public = UserPublicWithGroups(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin,
            is_active=user.is_active,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            source=user.source,
            require_password_change=user.require_password_change,
            is_system=user.is_system,
            role=user.role,
            cluster_id=user.cluster_id,
            tenant_id=user.tenant_id,
            worker_id=user.worker_id,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

        # Get user groups using User model's relationship
        try:
            # Query user_group_members and user_groups tables
            from sqlalchemy.orm import selectinload

            # Get user with user groups
            user_with_groups = await session.get(
                User,
                user.id,
                options=[
                    selectinload(User.user_groups).selectinload(
                        UserGroupMember.user_group
                    )
                ],
            )

            if user_with_groups and user_with_groups.user_groups:
                for member in user_with_groups.user_groups:
                    if member.user_group:
                        user_public.user_groups.append(
                            {
                                "id": member.user_group.id,
                                "name": member.user_group.name,
                                "description": member.user_group.description,
                                "status": member.user_group.status,
                            }
                        )
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.info(f"Error getting user groups: {e}")

        user_public_list.append(user_public)

    # Create new PaginatedList with UserPublicWithGroups models
    from gpustack.schemas.common import PaginatedList

    return PaginatedList[UserPublicWithGroups](
        items=user_public_list, pagination=result.pagination
    )


@router.get("/{id}", response_model=UserPublicWithGroups)
async def get_user(session: SessionDep, current_user: CurrentUserDep, id: int):
    user = await User.one_by_id(session, id)
    if not user:
        raise NotFoundException(message="User not found")

    # Only allow access to users in the same tenant
    if user.tenant_id != current_user.tenant_id:
        raise NotFoundException(message="User not found")

    # Create UserPublicWithGroups model
    user_public = UserPublicWithGroups(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        source=user.source,
        require_password_change=user.require_password_change,
        is_system=user.is_system,
        role=user.role,
        cluster_id=user.cluster_id,
        tenant_id=user.tenant_id,
        worker_id=user.worker_id,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )

    # Get user groups using User model's relationship
    try:
        # Query user_group_members and user_groups tables
        from sqlalchemy.orm import selectinload

        # Get user with user groups
        user_with_groups = await session.get(
            User,
            user.id,
            options=[
                selectinload(User.user_groups).selectinload(UserGroupMember.user_group)
            ],
        )

        if user_with_groups and user_with_groups.user_groups:
            for member in user_with_groups.user_groups:
                if member.user_group:
                    user_public.user_groups.append(
                        {
                            "id": member.user_group.id,
                            "name": member.user_group.name,
                            "description": member.user_group.description,
                            "status": member.user_group.status,
                        }
                    )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Error getting user groups: {e}")

    return user_public


@router.post("", response_model=UserPublicWithGroups)
async def create_user(
    session: SessionDep, current_user: CurrentUserDep, user_in: UserCreate
):
    existing = await User.one_by_field(session, "username", user_in.username)
    if existing:
        raise AlreadyExistsException(message=f"User {user_in.username} already exists")

    try:
        to_create = User(
            username=user_in.username,
            full_name=user_in.full_name,
            is_admin=user_in.is_admin,
            is_active=user_in.is_active,
            tenant_id=current_user.tenant_id,
        )
        if user_in.password:
            to_create.hashed_password = get_secret_hash(user_in.password)
        user = await User.create(session, to_create)
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to create user: {e}")

    # Add user to specified user groups if any
    user_groups = []
    if user_in.user_group_ids:
        # Get valid user groups that belong to the same tenant
        valid_groups = await session.exec(
            select(UserGroup)
            .where(UserGroup.id.in_(user_in.user_group_ids))
            .where(UserGroup.tenant_id == current_user.tenant_id)
            .where(UserGroup.deleted_at.is_(None))
        )
        valid_groups = valid_groups.all()

        if valid_groups:
            for group in valid_groups:
                # Check if user is already in the group
                existing_member = await session.exec(
                    select(UserGroupMember)
                    .where(UserGroupMember.user_group_id == group.id)
                    .where(UserGroupMember.user_id == user.id)
                )

                if not existing_member.first():
                    # Add user to the group
                    member = UserGroupMember(user_group_id=group.id, user_id=user.id)
                    session.add(member)
                    # Add to user_groups list
                    user_groups.append(
                        {
                            "id": group.id,
                            "name": group.name,
                            "description": group.description,
                            "status": group.status,
                        }
                    )

            # Commit the group membership changes
            await session.commit()
            # Refresh the user to get the latest data
            await session.refresh(user)

    # Create UserPublicWithGroups model
    user_public = UserPublicWithGroups(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        source=user.source,
        require_password_change=user.require_password_change,
        is_system=user.is_system,
        role=user.role,
        cluster_id=user.cluster_id,
        tenant_id=user.tenant_id,
        worker_id=user.worker_id,
        created_at=user.created_at,
        updated_at=user.updated_at,
        user_groups=user_groups,
    )

    return user_public


@router.put("/{id}", response_model=UserPublicWithGroups)
async def update_user(
    session: SessionDep, current_user: CurrentUserDep, id: int, user_in: UserUpdate
):
    user = await User.one_by_id(session, id)
    if not user:
        raise NotFoundException(message="User not found")

    # Only allow update to users in the same tenant
    if user.tenant_id != current_user.tenant_id:
        raise NotFoundException(message="User not found")

    if (
        user.is_active
        and user_in.is_active is False
        and await is_only_admin_user(session, user)
    ):
        raise ConflictException(message="Cannot deactivate the only admin user")

    try:
        update_data = user_in.model_dump()
        if user_in.password:
            hashed_password = get_secret_hash(user_in.password)
            update_data["hashed_password"] = hashed_password
        del update_data["password"]
        del update_data["source"]
        # Ensure tenant_id cannot be changed
        update_data["tenant_id"] = current_user.tenant_id
        # Fix foreign key constraints: set 0 values to None
        if update_data.get("cluster_id") == 0:
            update_data["cluster_id"] = None
        if update_data.get("worker_id") == 0:
            update_data["worker_id"] = None
        await user.update(session, update_data)
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to update user: {e}")

    # Create UserPublicWithGroups model
    user_public = UserPublicWithGroups(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        source=user.source,
        require_password_change=user.require_password_change,
        is_system=user.is_system,
        role=user.role,
        cluster_id=user.cluster_id,
        tenant_id=user.tenant_id,
        worker_id=user.worker_id,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )

    # Get user groups using User model's relationship
    try:
        # Query user_group_members and user_groups tables
        from sqlalchemy.orm import selectinload

        # Get user with user groups
        user_with_groups = await session.get(
            User,
            user.id,
            options=[
                selectinload(User.user_groups).selectinload(UserGroupMember.user_group)
            ],
        )

        if user_with_groups and user_with_groups.user_groups:
            for member in user_with_groups.user_groups:
                if member.user_group:
                    user_public.user_groups.append(
                        {
                            "id": member.user_group.id,
                            "name": member.user_group.name,
                            "description": member.user_group.description,
                            "status": member.user_group.status,
                        }
                    )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Error getting user groups: {e}")

    return user_public


@router.patch("/{id}/activation", response_model=UserPublicWithGroups)
async def update_user_activation(
    session: SessionDep,
    current_user: CurrentUserDep,
    id: int,
    activation_data: UserActivationUpdate,
):
    """
    Activate or deactivate a user account.
    Only administrators can perform this action.
    """
    user = await User.one_by_id(session, id)
    if not user:
        raise NotFoundException(message="User not found")

    # Only allow activation/deactivation of users in the same tenant
    if user.tenant_id != current_user.tenant_id:
        raise NotFoundException(message="User not found")

    if (
        user.is_active
        and activation_data.is_active is False
        and await is_only_admin_user(session, user)
    ):
        raise ConflictException(message="Cannot deactivate the only admin user")

    try:
        await user.update(session, {"is_active": activation_data.is_active})
    except Exception as e:
        raise InternalServerErrorException(
            message=f"Failed to update user activation: {e}"
        )

    # Create UserPublicWithGroups model
    user_public = UserPublicWithGroups(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        source=user.source,
        require_password_change=user.require_password_change,
        is_system=user.is_system,
        role=user.role,
        cluster_id=user.cluster_id,
        tenant_id=user.tenant_id,
        worker_id=user.worker_id,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )

    # Get user groups using User model's relationship
    try:
        # Query user_group_members and user_groups tables
        from sqlalchemy.orm import selectinload

        # Get user with user groups
        user_with_groups = await session.get(
            User,
            user.id,
            options=[
                selectinload(User.user_groups).selectinload(UserGroupMember.user_group)
            ],
        )

        if user_with_groups and user_with_groups.user_groups:
            for member in user_with_groups.user_groups:
                if member.user_group:
                    user_public.user_groups.append(
                        {
                            "id": member.user_group.id,
                            "name": member.user_group.name,
                            "description": member.user_group.description,
                            "status": member.user_group.status,
                        }
                    )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Error getting user groups: {e}")

    return user_public


@router.delete("/{id}")
async def delete_user(session: SessionDep, current_user: CurrentUserDep, id: int):
    # Get user directly from session (not through user_service which expunges it)
    from sqlmodel import select
    from gpustack.schemas.users import User
    from gpustack.schemas.user_groups import UserGroupMember

    user_stmt = select(User).where(User.id == id)
    user_result = await session.exec(user_stmt)
    user = user_result.first()

    if not user:
        raise NotFoundException(message="User not found")

    # Only allow deletion of users in the same tenant
    if user.tenant_id != current_user.tenant_id:
        raise NotFoundException(message="User not found")

    if await is_only_admin_user(session, user):
        raise ConflictException(message="Cannot delete the only admin user")

    try:
        # Delete user group members first
        member_stmt = select(UserGroupMember).where(UserGroupMember.user_id == id)
        members = await session.exec(member_stmt)
        members = members.all()

        # Delete each member
        for member in members:
            await session.delete(member)

        # Delete the user
        await session.delete(user)

        # Commit all changes
        await session.commit()

        # Clear cache
        user_service = UserService(session)
        await delete_cache_by_key(user_service.get_by_id, id)
        await delete_cache_by_key(user_service.get_user_accessible_model_names, id)
        await delete_cache_by_key(user_service.get_by_username, user.username)

        # Clear API key caches
        from gpustack.server.services import APIKeyService

        apikeys = await APIKeyService(session).get_by_user_id(id)
        for apikey in apikeys:
            await delete_cache_by_key(
                APIKeyService.get_by_access_key, apikey.access_key
            )
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to delete user: {e}")


async def is_only_admin_user(session: SessionDep, user: User) -> bool:
    if not user.is_admin:
        return False
    admin_count = await User.count_by_fields(
        session, {"is_admin": True, "is_active": True}
    )
    return admin_count == 1


me_router = APIRouter()


@me_router.get("/me", response_model=UserPublic)
async def get_user_me(user: CurrentUserDep):
    return user


@me_router.put("/me", response_model=UserPublic)
async def update_user_me(
    session: SessionDep, user: CurrentUserDep, user_in: UserSelfUpdate
):
    try:
        update_data = user_in.model_dump(exclude_none=True)
        if "password" in update_data:
            hashed_password = get_secret_hash(update_data["password"])
            update_data["hashed_password"] = hashed_password
            del update_data["password"]
        await UserService(session).update(user, update_data)
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to update user: {e}")

    return user
