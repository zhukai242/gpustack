from typing import List, Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from gpustack.schemas.rack import Rack, RackCreate, RackUpdate


class RackService:
    """Service for managing racks."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, rack_create: RackCreate) -> Rack:
        """Create a new rack."""
        rack = Rack(**rack_create.model_dump())
        self._session.add(rack)
        await self._session.flush()
        return rack

    async def create_many(self, rack_creates: List[RackCreate]) -> List[Rack]:
        """Create multiple racks."""
        racks = [Rack(**rack_create.model_dump()) for rack_create in rack_creates]
        self._session.add_all(racks)
        await self._session.flush()
        return racks

    async def get_by_id(self, rack_id: int) -> Optional[Rack]:
        """Get a rack by ID."""
        return await Rack.one_by_id(self._session, rack_id)

    async def get_by_cluster_id(self, cluster_id: int) -> List[Rack]:
        """Get all racks for a cluster."""
        return await Rack.all(self._session, cluster_id=cluster_id, deleted_at=None)

    async def update(self, rack_id: int, rack_update: RackUpdate) -> Optional[Rack]:
        """Update a rack."""
        rack = await self.get_by_id(rack_id)
        if not rack:
            return None
        update_data = rack_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(rack, key, value)
        await rack.save(self._session)
        return rack

    async def delete(self, rack_id: int) -> Optional[Rack]:
        """Delete a rack."""
        rack = await self.get_by_id(rack_id)
        if not rack:
            return None
        await rack.delete(self._session)
        return rack
