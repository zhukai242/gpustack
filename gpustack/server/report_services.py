import os
import csv
from datetime import datetime
from typing import Optional, List
from sqlmodel import select, func, and_
from gpustack.schemas.reports import (
    Report,
    ReportCreate,
    ReportUpdate,
    ReportDetail,
    ReportDetailBase,
    ReportTypeEnum,
    ReportStatusEnum,
)
from gpustack.schemas.load import WorkerLoad, GPULoad
from gpustack.schemas.workers import Worker
from sqlmodel.ext.asyncio.session import AsyncSession


class ReportService:
    """Service for managing reports."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _convert_to_report_type(self, report_type_input) -> ReportTypeEnum:
        """Convert input to ReportTypeEnum."""
        if isinstance(report_type_input, ReportTypeEnum):
            return report_type_input
        elif isinstance(report_type_input, str):
            lowercase_type = report_type_input.lower()
            if lowercase_type == 'gpu':
                return ReportTypeEnum.gpu
            elif lowercase_type == 'worker':
                return ReportTypeEnum.worker
            else:
                raise ValueError(f"Invalid report type: {report_type_input}")
        else:
            lowercase_type = str(report_type_input).lower()
            if lowercase_type == 'gpu':
                return ReportTypeEnum.gpu
            elif lowercase_type == 'worker':
                return ReportTypeEnum.worker
            else:
                raise ValueError(f"Invalid report type: {report_type_input}")

    def _convert_to_report_status(self, report_status_input) -> ReportStatusEnum:
        """Convert input to ReportStatusEnum."""
        if isinstance(report_status_input, ReportStatusEnum):
            return report_status_input
        elif isinstance(report_status_input, str):
            lowercase_status = report_status_input.lower()
            if lowercase_status == 'pending':
                return ReportStatusEnum.pending
            elif lowercase_status == 'generating':
                return ReportStatusEnum.generating
            elif lowercase_status == 'completed':
                return ReportStatusEnum.completed
            elif lowercase_status == 'failed':
                return ReportStatusEnum.failed
            else:
                raise ValueError(f"Invalid report status: {report_status_input}")
        else:
            lowercase_status = str(report_status_input).lower()
            if lowercase_status == 'pending':
                return ReportStatusEnum.pending
            elif lowercase_status == 'generating':
                return ReportStatusEnum.generating
            elif lowercase_status == 'completed':
                return ReportStatusEnum.completed
            elif lowercase_status == 'failed':
                return ReportStatusEnum.failed
            else:
                raise ValueError(f"Invalid report status: {report_status_input}")

    async def create(self, report_create: ReportCreate) -> Report:
        """Create a new report."""
        # Convert report type and status to enums
        report_type = self._convert_to_report_type(report_create.type)
        report_status = self._convert_to_report_status(report_create.status)

        # Create report data with enum values
        report_data = {
            "name": report_create.name,
            "type": report_type,
            "start_time": report_create.start_time,
            "end_time": report_create.end_time,
            "user_group_id": report_create.user_group_id,
            "status": report_status,
            "file_path": report_create.file_path,
            "description": report_create.description,
        }

        # Create report object
        report = Report(**report_data)

        # Add to session and commit
        try:
            self.session.add(report)
            await self.session.commit()
            await self.session.refresh(report)
            return report
        except Exception as e:
            # If any error occurs, rollback the session
            await self.session.rollback()
            raise e

    async def get_by_id(self, report_id: int) -> Optional[Report]:
        """
        Get a report by ID.
        """
        return await Report.one_by_id(self.session, report_id)

    async def update(
        self, report_id: int, report_update: ReportUpdate
    ) -> Optional[Report]:
        """
        Update a report.
        """
        report = await self.get_by_id(report_id)
        if not report:
            return None

        update_data = report_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(report, field, value)

        await self.session.commit()
        await self.session.refresh(report)
        return report

    async def generate_report(self, report_id: int) -> Optional[Report]:
        """
        Generate a report by ID.
        """
        report = await self.get_by_id(report_id)
        if not report:
            return None

        # Update report status to generating
        await self.update(report_id, ReportUpdate(status=ReportStatusEnum.generating))

        try:
            # Generate report based on type
            if report.type == ReportTypeEnum.gpu:
                await self._generate_gpu_report(report)
            elif report.type == ReportTypeEnum.worker:
                await self._generate_worker_report(report)
            else:
                raise ValueError(f"Unknown report type: {report.type}")

            # Update report status to completed
            await self.update(
                report_id, ReportUpdate(status=ReportStatusEnum.completed)
            )
        except Exception as e:
            # Update report status to failed
            await self.update(report_id, ReportUpdate(status=ReportStatusEnum.failed))
            raise e

        return report

    async def _generate_gpu_report(self, report: Report) -> None:
        """Generate GPU resource report."""
        # Get all resources for the user group
        resources = await self._get_resources_for_user_group(report.user_group_id)
        gpu_ids = [r.gpu_id for r in resources if r.gpu_id]
        worker_ids = [r.worker_id for r in resources]

        # Get GPU load data
        gpu_loads = await self._get_gpu_loads(
            gpu_ids, worker_ids, report.start_time, report.end_time
        )

        # Generate report file
        file_path = await self._generate_gpu_report_file(report, gpu_loads, resources)

        # Update report with file path
        await self.update(report.id, ReportUpdate(file_path=file_path))

        # Save report details to database
        # await self._save_gpu_report_details(report, gpu_loads, resources)

    async def _generate_worker_report(self, report: Report) -> None:
        """Generate worker resource report."""
        # Get all resources for the user group
        resources = await self._get_resources_for_user_group(report.user_group_id)
        worker_ids = list(set([r.worker_id for r in resources]))

        # Get worker load data
        worker_loads = await self._get_worker_loads(
            worker_ids, report.start_time, report.end_time
        )

        # Generate report file
        file_path = await self._generate_worker_report_file(
            report, worker_loads, resources
        )

        # Update report with file path
        await self.update(report.id, ReportUpdate(file_path=file_path))

        # Save report details to database
        # await self._save_worker_report_details(report, worker_loads, resources)

    async def _get_resources_for_user_group(self, user_group_id: Optional[int]) -> List:
        """Get all resources for a user group."""
        from gpustack.schemas.tenants import TenantResource

        if not user_group_id:
            # If no user group, get all resources
            return await TenantResource.all_by_fields(
                self.session, fields={"deleted_at": None}
            )

        # Get resources for the user group
        # This is a placeholder - need to implement actual logic to get resources by user group
        # For now, return all resources
        return await TenantResource.all_by_fields(
            self.session, fields={"deleted_at": None}
        )

    async def _get_gpu_loads(
        self,
        gpu_ids: List[str],
        worker_ids: List[int],
        start_time: datetime,
        end_time: datetime,
    ) -> List[GPULoad]:
        """Get GPU load data for specified GPU IDs, worker IDs, and time range."""
        if not gpu_ids and not worker_ids:
            return []

        # Convert datetime objects to Unix timestamps
        start_timestamp = int(start_time.timestamp())
        end_timestamp = int(end_time.timestamp())

        conditions = []
        if gpu_ids:
            conditions.append(GPULoad.gpu_id.in_(gpu_ids))
        if worker_ids:
            conditions.append(GPULoad.worker_id.in_(worker_ids))
        conditions.append(GPULoad.timestamp >= start_timestamp)
        conditions.append(GPULoad.timestamp <= end_timestamp)

        stmt = select(GPULoad).where(and_(*conditions)).order_by(GPULoad.timestamp)
        result = await self.session.exec(stmt)
        return result.all()

    async def _get_worker_loads(
        self, worker_ids: List[int], start_time: datetime, end_time: datetime
    ) -> List[WorkerLoad]:
        """Get worker load data for specified worker IDs and time range."""
        if not worker_ids:
            return []

        # Convert datetime objects to Unix timestamps
        start_timestamp = int(start_time.timestamp())
        end_timestamp = int(end_time.timestamp())

        stmt = (
            select(WorkerLoad)
            .where(
                and_(
                    WorkerLoad.worker_id.in_(worker_ids),
                    WorkerLoad.timestamp >= start_timestamp,
                    WorkerLoad.timestamp <= end_timestamp,
                )
            )
            .order_by(WorkerLoad.timestamp)
        )
        result = await self.session.exec(stmt)
        return result.all()

    async def _generate_gpu_report_file(
        self, report: Report, gpu_loads: List[GPULoad], resources: List
    ) -> str:
        """Generate GPU report file in CSV format."""
        # Create reports directory if it doesn't exist
        reports_dir = os.path.join(os.getcwd(), "reports")
        os.makedirs(reports_dir, exist_ok=True)

        # Generate file name
        file_name = (
            f"gpu_report_{report.id}_{report.start_time.strftime('%Y%m%d_%H%M%S')}.csv"
        )
        file_path = os.path.join(reports_dir, file_name)

        # Get resource mapping
        resource_map = {r.gpu_id: r for r in resources if r.gpu_id}

        # Write CSV file
        with open(file_path, "w", newline="") as csvfile:
            fieldnames = [
                "timestamp",
                "gpu_id",
                "worker_id",
                "gpu_index",
                "gpu_utilization",
                "vram_utilization",
                "resource_id",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for load in gpu_loads:
                writer.writerow(
                    {
                        "timestamp": datetime.fromtimestamp(load.timestamp).isoformat(),
                        "gpu_id": load.gpu_id,
                        "worker_id": load.worker_id,
                        "gpu_index": load.gpu_index,
                        "gpu_utilization": load.gpu_utilization,
                        "vram_utilization": load.vram_utilization,
                        "resource_id": (
                            resource_map.get(load.gpu_id, {}).id
                            if resource_map.get(load.gpu_id)
                            else ""
                        ),
                    }
                )

        return file_path

    async def _generate_worker_report_file(
        self, report: Report, worker_loads: List[WorkerLoad], resources: List
    ) -> str:
        """Generate worker report file in CSV format."""
        # Create reports directory if it doesn't exist
        reports_dir = os.path.join(os.getcwd(), "reports")
        os.makedirs(reports_dir, exist_ok=True)

        # Generate file name
        file_name = (
            f"worker_report_{report.id}_"
            f"{report.start_time.strftime('%Y%m%d_%H%M%S')}.csv"
        )
        file_path = os.path.join(reports_dir, file_name)

        # Get unique worker IDs
        worker_ids = list(set([r.worker_id for r in resources]))
        # Get workers info
        stmt = select(Worker).where(Worker.id.in_(worker_ids))
        workers_result = await self.session.exec(stmt)
        workers = workers_result.all()
        worker_map = {w.id: w for w in workers}

        # Write CSV file
        with open(file_path, "w", newline="") as csvfile:
            fieldnames = [
                "timestamp",
                "worker_id",
                "worker_name",
                "cpu",
                "ram",
                "gpu",
                "vram",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for load in worker_loads:
                writer.writerow(
                    {
                        "timestamp": datetime.fromtimestamp(load.timestamp).isoformat(),
                        "worker_id": load.worker_id,
                        "worker_name": (
                            worker_map.get(load.worker_id, {}).name
                            if worker_map.get(load.worker_id)
                            else ""
                        ),
                        "cpu": load.cpu,
                        "ram": load.ram,
                        "gpu": load.gpu,
                        "vram": load.vram,
                    }
                )

        return file_path

    async def _save_gpu_report_details(
        self, report: Report, gpu_loads: List[GPULoad], resources: List
    ) -> None:
        """Save GPU report details to database."""
        # Create report details
        report_details = []
        for load in gpu_loads:
            # Convert Unix timestamp to datetime
            load_timestamp = datetime.fromtimestamp(load.timestamp)

            # GPU utilization
            gpu_util_detail = ReportDetailBase(
                metric_name="gpu_utilization",
                metric_value=load.gpu_utilization if load.gpu_utilization else 0.0,
                metric_unit="%",
                timestamp=load_timestamp,
                resource_id=load.gpu_id,
                resource_name=load.gpu_id,
                user_group_id=report.user_group_id,
                user_group_name="",
            )
            report_details.append(gpu_util_detail)

            # VRAM utilization
            vram_util_detail = ReportDetailBase(
                metric_name="vram_utilization",
                metric_value=load.vram_utilization if load.vram_utilization else 0.0,
                metric_unit="%",
                timestamp=load_timestamp,
                resource_id=load.gpu_id,
                resource_name=load.gpu_id,
                user_group_id=report.user_group_id,
                user_group_name="",
            )
            report_details.append(vram_util_detail)

        # Bulk insert report details
        if report_details:
            await self._bulk_create_report_details(report, report_details)

    async def _save_worker_report_details(
        self, report: Report, worker_loads: List[WorkerLoad], resources: List
    ) -> None:
        """Save worker report details to database."""
        # Get workers info
        worker_ids = list(set([r.worker_id for r in resources]))
        stmt = select(Worker).where(Worker.id.in_(worker_ids))
        workers_result = await self.session.exec(stmt)
        workers = workers_result.all()
        worker_map = {w.id: w for w in workers}

        # Create report details
        report_details = []
        for load in worker_loads:
            # Convert Unix timestamp to datetime
            load_timestamp = datetime.fromtimestamp(load.timestamp)

            # CPU utilization
            cpu_detail = ReportDetailBase(
                metric_name="cpu_utilization",
                metric_value=load.cpu if load.cpu else 0.0,
                metric_unit="%",
                timestamp=load_timestamp,
                resource_id=str(load.worker_id),
                resource_name=(
                    worker_map.get(load.worker_id, {}).name
                    if worker_map.get(load.worker_id)
                    else ""
                ),
                user_group_id=report.user_group_id,
                user_group_name="",
            )
            report_details.append(cpu_detail)

            # RAM utilization
            ram_detail = ReportDetailBase(
                metric_name="ram_utilization",
                metric_value=load.ram if load.ram else 0.0,
                metric_unit="%",
                timestamp=load_timestamp,
                resource_id=str(load.worker_id),
                resource_name=(
                    worker_map.get(load.worker_id, {}).name
                    if worker_map.get(load.worker_id)
                    else ""
                ),
                user_group_id=report.user_group_id,
                user_group_name="",
            )
            report_details.append(ram_detail)

            # GPU utilization
            gpu_detail = ReportDetailBase(
                metric_name="gpu_utilization",
                metric_value=load.gpu if load.gpu else 0.0,
                metric_unit="%",
                timestamp=load_timestamp,
                resource_id=str(load.worker_id),
                resource_name=(
                    worker_map.get(load.worker_id, {}).name
                    if worker_map.get(load.worker_id)
                    else ""
                ),
                user_group_id=report.user_group_id,
                user_group_name="",
            )
            report_details.append(gpu_detail)

            # VRAM utilization
            vram_detail = ReportDetailBase(
                metric_name="vram_utilization",
                metric_value=load.vram if load.vram else 0.0,
                metric_unit="%",
                timestamp=load_timestamp,
                resource_id=str(load.worker_id),
                resource_name=(
                    worker_map.get(load.worker_id, {}).name
                    if worker_map.get(load.worker_id)
                    else ""
                ),
                user_group_id=report.user_group_id,
                user_group_name="",
            )
            report_details.append(vram_detail)

        # Bulk insert report details
        if report_details:
            await self._bulk_create_report_details(report, report_details)

    async def _bulk_create_report_details(
        self, report: Report, report_details: List[ReportDetailBase]
    ) -> None:
        """Bulk create report details."""
        # Create ReportDetail objects
        details = []
        for detail in report_details:
            report_detail = ReportDetail(**detail.model_dump(), report_id=report.id)
            details.append(report_detail)

        # Bulk insert
        self.session.add_all(details)
        await self.session.commit()

    async def list(self, skip: int = 0, limit: int = 100, **filters) -> List[Report]:
        """List reports with optional filters."""
        statement = select(Report)
        for key, value in filters.items():
            if isinstance(value, list):
                statement = statement.where(getattr(Report, key).in_(value))
            else:
                statement = statement.where(getattr(Report, key) == value)

        statement = statement.offset(skip).limit(limit)
        result = await self.session.exec(statement)
        return result.all()

    async def count(self, **filters) -> int:
        """Count reports with optional filters."""
        stmt = select(func.count(Report.id)).where(
            and_(*[getattr(Report, field) == value for field, value in filters.items()])
        )
        result = await self.session.exec(stmt)
        return result.one()
