from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from gpustack.api.exceptions import (
    AlreadyExistsException,
    InternalServerErrorException,
    NotFoundException,
    ConflictException,
)
from gpustack.security import get_secret_hash
from gpustack.server.deps import CurrentUserDep, SessionDep, EngineDep
from gpustack.schemas.users import (
    User,
    UserActivationUpdate,
    UserCreate,
    UserListParams,
    UserUpdate,
    UserPublic,
    UsersPublic,
    UserSelfUpdate,
)
from gpustack.schemas.user_groups import UserGroup, UserGroupMember
from sqlmodel import select
from gpustack.server.services import UserService

router = APIRouter()


@router.get("", response_model=UsersPublic)
async def get_users(
    engine: EngineDep,
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
            User.streaming(engine, fuzzy_fields=fuzzy_fields, fields=fields),
            media_type="text/event-stream",
        )

    return await User.paginated_by_query(
        session=session,
        fuzzy_fields=fuzzy_fields,
        page=params.page,
        per_page=params.perPage,
        fields=fields,
        order_by=params.order_by,
    )


@router.get("/{id}", response_model=UserPublic)
async def get_user(session: SessionDep, current_user: CurrentUserDep, id: int):
    user = await User.one_by_id(session, id)
    if not user:
        raise NotFoundException(message="User not found")

    # Only allow access to users in the same tenant
    if user.tenant_id != current_user.tenant_id:
        raise NotFoundException(message="User not found")

    return user


@router.post("", response_model=UserPublic)
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

            # Commit the group membership changes
            await session.commit()
            # Refresh the user to get the latest data
            await session.refresh(user)

    return user


@router.put("/{id}", response_model=UserPublic)
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
        await user.update(session, update_data)
    except Exception as e:
        raise InternalServerErrorException(message=f"Failed to update user: {e}")

    return user


@router.patch("/{id}/activation", response_model=UserPublic)
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

    return user


@router.delete("/{id}")
async def delete_user(session: SessionDep, current_user: CurrentUserDep, id: int):
    user_service = UserService(session)
    user = await user_service.get_by_id(id)
    if not user:
        raise NotFoundException(message="User not found")

    # Only allow deletion of users in the same tenant
    if user.tenant_id != current_user.tenant_id:
        raise NotFoundException(message="User not found")

    if await is_only_admin_user(session, user):
        raise ConflictException(message="Cannot delete the only admin user")

    try:
        await user_service.delete(user)
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
