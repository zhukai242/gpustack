from typing import List, Optional
from datetime import datetime
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, and_, func

from gpustack.schemas.tenants import (
    Tenant,
    TenantCreate,
    TenantUpdate,
    TenantResource,
    TenantResourceCreate,
    TenantResourceUpdate,
    TenantResourceAdjustment,
    TenantResourceAdjustmentCreate,
    TenantResourceUsageDetail,
    TenantResourceUsageDetailCreate,
    TenantStatusEnum,
)


class TenantService:
    """Service for managing tenants."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, tenant_create: TenantCreate) -> Tenant:
        """Create a new tenant."""
        tenant = Tenant(**tenant_create.model_dump())
        self._session.add(tenant)
        await self._session.flush()
        await self._session.refresh(tenant)
        return tenant

    async def get_by_id(self, tenant_id: int) -> Optional[Tenant]:
        """Get a tenant by ID."""
        return await Tenant.one_by_id(self._session, tenant_id)

    async def get_by_name(self, name: str) -> Optional[Tenant]:
        """Get a tenant by name."""
        return await Tenant.one_by_field(self._session, "name", name)

    async def list_all(
        self,
        status: Optional[TenantStatusEnum] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Tenant]:
        """List all tenants with optional filters."""
        fields = {"deleted_at": None}
        if status:
            fields["status"] = status
        return await Tenant.all_by_fields(
            self._session, fields=fields, skip=skip, limit=limit
        )

    async def update(
        self, tenant_id: int, tenant_update: TenantUpdate
    ) -> Optional[Tenant]:
        """Update a tenant."""
        tenant = await self.get_by_id(tenant_id)
        if not tenant or tenant.deleted_at:
            return None

        update_data = tenant_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(tenant, key, value)

        await tenant.save(self._session)
        return tenant

    async def delete(self, tenant_id: int) -> Optional[Tenant]:
        """Soft delete a tenant."""
        tenant = await self.get_by_id(tenant_id)
        if not tenant or tenant.deleted_at:
            return None
        await tenant.delete(self._session)
        return tenant

    async def check_resource_expiry(self, tenant_id: int) -> bool:
        """Check if tenant's resources have expired."""
        tenant = await self.get_by_id(tenant_id)
        if not tenant:
            return False

        if tenant.resource_end_time and tenant.resource_end_time < datetime.now():
            return True
        return False

    async def update_status(
        self, tenant_id: int, status: TenantStatusEnum
    ) -> Optional[Tenant]:
        """Update tenant status."""
        tenant = await self.get_by_id(tenant_id)
        if not tenant or tenant.deleted_at:
            return None

        tenant.status = status
        await tenant.save(self._session)
        return tenant


class TenantResourceService:
    """Service for managing tenant resource allocations."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, resource_create: TenantResourceCreate) -> TenantResource:
        """Create a new tenant resource allocation."""
        resource = TenantResource(**resource_create.model_dump())
        self._session.add(resource)
        await self._session.flush()
        await self._session.refresh(resource)
        return resource

    async def create_many(
        self, resource_creates: List[TenantResourceCreate]
    ) -> List[TenantResource]:
        """Create multiple tenant resource allocations."""
        resources = [TenantResource(**rc.model_dump()) for rc in resource_creates]
        self._session.add_all(resources)
        await self._session.flush()
        for resource in resources:
            await self._session.refresh(resource)
        return resources

    async def get_by_id(self, resource_id: int) -> Optional[TenantResource]:
        """Get a tenant resource by ID."""
        return await TenantResource.one_by_id(self._session, resource_id)

    async def get_by_tenant_id(self, tenant_id: int) -> List[TenantResource]:
        """Get all resources for a tenant."""
        return await TenantResource.all_by_fields(
            self._session, fields={"tenant_id": tenant_id, "deleted_at": None}
        )

    async def get_by_worker_id(self, worker_id: int) -> List[TenantResource]:
        """Get all resources allocated on a worker."""
        return await TenantResource.all_by_fields(
            self._session, fields={"worker_id": worker_id, "deleted_at": None}
        )

    async def get_active_resources(
        self, tenant_id: Optional[int] = None
    ) -> List[TenantResource]:
        """Get all active resources (not expired)."""
        stmt = select(TenantResource).where(
            and_(
                TenantResource.deleted_at.is_(None),
                TenantResource.resource_end_time.is_(None)
                | (TenantResource.resource_end_time > datetime.now()),
            )
        )

        if tenant_id:
            stmt = stmt.where(TenantResource.tenant_id == tenant_id)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self, resource_id: int, resource_update: TenantResourceUpdate
    ) -> Optional[TenantResource]:
        """Update a tenant resource allocation."""
        resource = await self.get_by_id(resource_id)
        if not resource or resource.deleted_at:
            return None

        update_data = resource_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(resource, key, value)

        await resource.save(self._session)
        return resource

    async def delete(self, resource_id: int) -> Optional[TenantResource]:
        """Soft delete a tenant resource allocation."""
        resource = await self.get_by_id(resource_id)
        if not resource or resource.deleted_at:
            return None
        await resource.delete(self._session)
        return resource


class TenantResourceAdjustmentService:
    """Service for managing tenant resource adjustment records."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self, adjustment_create: TenantResourceAdjustmentCreate
    ) -> TenantResourceAdjustment:
        """Create a new resource adjustment record."""
        adjustment = TenantResourceAdjustment(**adjustment_create.model_dump())
        self._session.add(adjustment)
        await self._session.flush()
        await self._session.refresh(adjustment)
        return adjustment

    async def get_by_id(self, adjustment_id: int) -> Optional[TenantResourceAdjustment]:
        """Get a resource adjustment by ID."""
        return await TenantResourceAdjustment.one_by_id(self._session, adjustment_id)

    async def get_by_tenant_id(
        self, tenant_id: int, skip: int = 0, limit: int = 100
    ) -> List[TenantResourceAdjustment]:
        """Get all adjustment records for a tenant."""
        return await TenantResourceAdjustment.all_by_fields(
            self._session,
            fields={"tenant_id": tenant_id, "deleted_at": None},
            skip=skip,
            limit=limit,
        )

    async def get_by_time_range(
        self,
        tenant_id: int,
        start_time: datetime,
        end_time: datetime,
    ) -> List[TenantResourceAdjustment]:
        """Get adjustment records within a time range."""
        stmt = select(TenantResourceAdjustment).where(
            and_(
                TenantResourceAdjustment.tenant_id == tenant_id,
                TenantResourceAdjustment.deleted_at.is_(None),
                TenantResourceAdjustment.adjustment_time >= start_time,
                TenantResourceAdjustment.adjustment_time <= end_time,
            )
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class TenantResourceUsageDetailService:
    """Service for managing tenant resource usage details."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self, usage_create: TenantResourceUsageDetailCreate
    ) -> TenantResourceUsageDetail:
        """Create a new usage detail record."""
        usage = TenantResourceUsageDetail(**usage_create.model_dump())
        self._session.add(usage)
        await self._session.flush()
        await self._session.refresh(usage)
        return usage

    async def create_many(
        self, usage_creates: List[TenantResourceUsageDetailCreate]
    ) -> List[TenantResourceUsageDetail]:
        """Create multiple usage detail records."""
        usages = [TenantResourceUsageDetail(**uc.model_dump()) for uc in usage_creates]
        self._session.add_all(usages)
        await self._session.flush()
        for usage in usages:
            await self._session.refresh(usage)
        return usages

    async def get_by_id(self, usage_id: int) -> Optional[TenantResourceUsageDetail]:
        """Get a usage detail by ID."""
        return await TenantResourceUsageDetail.one_by_id(self._session, usage_id)

    async def get_by_tenant_and_date(
        self, tenant_id: int, usage_date: datetime
    ) -> List[TenantResourceUsageDetail]:
        """Get usage details for a tenant on a specific date."""
        return await TenantResourceUsageDetail.all_by_fields(
            self._session,
            fields={
                "tenant_id": tenant_id,
                "usage_date": usage_date,
                "deleted_at": None,
            },
        )

    async def get_by_date_range(
        self,
        tenant_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> List[TenantResourceUsageDetail]:
        """Get usage details within a date range."""
        stmt = (
            select(TenantResourceUsageDetail)
            .where(
                and_(
                    TenantResourceUsageDetail.tenant_id == tenant_id,
                    TenantResourceUsageDetail.deleted_at.is_(None),
                    TenantResourceUsageDetail.usage_date >= start_date,
                    TenantResourceUsageDetail.usage_date <= end_date,
                )
            )
            .order_by(TenantResourceUsageDetail.usage_date)
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_usage_summary(
        self,
        tenant_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> dict:
        """Get usage summary for a tenant within a date range."""
        stmt = select(
            func.sum(TenantResourceUsageDetail.gpu_hours).label("total_gpu_hours"),
            func.avg(TenantResourceUsageDetail.gpu_utilization).label(
                "avg_utilization"
            ),
            func.sum(TenantResourceUsageDetail.cost).label("total_cost"),
            func.count(TenantResourceUsageDetail.id).label("record_count"),
        ).where(
            and_(
                TenantResourceUsageDetail.tenant_id == tenant_id,
                TenantResourceUsageDetail.deleted_at.is_(None),
                TenantResourceUsageDetail.usage_date >= start_date,
                TenantResourceUsageDetail.usage_date <= end_date,
            )
        )

        result = await self._session.execute(stmt)
        row = result.one_or_none()

        if not row:
            return {
                "total_gpu_hours": 0.0,
                "avg_utilization": 0.0,
                "total_cost": 0.0,
                "record_count": 0,
            }

        return {
            "total_gpu_hours": float(row.total_gpu_hours or 0.0),
            "avg_utilization": float(row.avg_utilization or 0.0),
            "total_cost": float(row.total_cost or 0.0),
            "record_count": int(row.record_count or 0),
        }

    async def upsert_usage_detail(
        self, usage_create: TenantResourceUsageDetailCreate
    ) -> TenantResourceUsageDetail:
        """
        Upsert a usage detail record.
        If a record exists for the same tenant, date, worker, and GPU, update it.
        Otherwise, create a new record.
        """
        # Try to find existing record
        stmt = select(TenantResourceUsageDetail).where(
            and_(
                TenantResourceUsageDetail.tenant_id == usage_create.tenant_id,
                TenantResourceUsageDetail.usage_date == usage_create.usage_date,
                TenantResourceUsageDetail.worker_id == usage_create.worker_id,
                TenantResourceUsageDetail.gpu_id == usage_create.gpu_id,
                TenantResourceUsageDetail.deleted_at.is_(None),
            )
        )

        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing record
            update_data = usage_create.model_dump(
                exclude={"tenant_id", "usage_date", "worker_id", "gpu_id"}
            )
            for key, value in update_data.items():
                setattr(existing, key, value)
            await existing.save(self._session)
            return existing
        else:
            # Create new record
            return await self.create(usage_create)
