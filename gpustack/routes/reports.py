from typing import Optional
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlmodel import select
import os

from gpustack.api.exceptions import (
    NotFoundException,
    BadRequestException,
)
from gpustack.server.deps import SessionDep, CurrentUserDep
from gpustack.schemas.reports import (
    ReportGenerateRequest,
    ReportPublic,
    ReportsPublic,
    ReportListParams,
    ReportDetailsPublic,
    ReportDetailsListParams,
    ReportDetail,
)
from gpustack.server.report_services import ReportService

router = APIRouter()


@router.post("/generate", response_model=ReportPublic, status_code=201)
async def generate_report(
    request: ReportGenerateRequest, session: SessionDep, current_user: CurrentUserDep
):
    """Generate a new resource usage report."""
    from gpustack.schemas.reports import ReportCreate

    # Validate time range
    if request.end_time <= request.start_time:
        raise BadRequestException("End time must be after start time")

    # Create report name
    report_name = (
        f"{request.type.value}_report_"
        f"{request.start_time.strftime('%Y%m%d')}_"
        f"{request.end_time.strftime('%Y%m%d')}"
    )

    # Create report in database
    report_service = ReportService(session)
    report_create = ReportCreate(
        name=report_name,
        type=request.type,
        start_time=request.start_time,
        end_time=request.end_time,
        user_group_id=request.user_group_id,
        description=request.description,
    )
    report = await report_service.create(report_create)

    # Generate report asynchronously (in background)
    # For now, we'll generate it synchronously for simplicity
    await report_service.generate_report(report.id)

    return report


@router.get("", response_model=ReportsPublic)
async def list_reports(
    session: SessionDep,
    current_user: CurrentUserDep,
    params: ReportListParams = Depends(),
    type: Optional[str] = None,
    status: Optional[str] = None,
    user_group_id: Optional[int] = None,
):
    """List resource usage reports with optional filters."""
    fields = {"deleted_at": None}

    if type:
        fields["type"] = type
    if status:
        fields["status"] = status
    if user_group_id:
        fields["user_group_id"] = user_group_id

    # Get total count
    report_service = ReportService(session)
    total = await report_service.count(**fields)

    # Get paginated reports
    reports = await report_service.list(
        skip=(params.page - 1) * params.perPage, limit=params.perPage, **fields
    )

    return ReportsPublic(
        items=[ReportPublic.model_validate(report) for report in reports],
        total=total,
        page=params.page,
        perPage=params.perPage,
    )


@router.get("/{report_id}", response_model=ReportPublic)
async def get_report(report_id: int, session: SessionDep, current_user: CurrentUserDep):
    """Get a resource usage report by ID."""
    report_service = ReportService(session)
    report = await report_service.get_by_id(report_id)

    if not report:
        raise NotFoundException(f"Report with ID {report_id} not found")

    return ReportPublic.model_validate(report)


@router.get("/{report_id}/details", response_model=ReportDetailsPublic)
async def get_report_details(
    report_id: int,
    session: SessionDep,
    current_user: CurrentUserDep,
    params: ReportDetailsListParams = Depends(),
    metric_name: Optional[str] = None,
    resource_id: Optional[str] = None,
):
    """Get details for a resource usage report."""
    # Check if report exists
    report_service = ReportService(session)
    report = await report_service.get_by_id(report_id)
    if not report:
        raise NotFoundException(f"Report with ID {report_id} not found")

    # Build query filters
    fields = {"report_id": report_id}
    if metric_name:
        fields["metric_name"] = metric_name
    if resource_id:
        fields["resource_id"] = resource_id

    # Get total count
    total_stmt = select(ReportDetail).where(
        *[getattr(ReportDetail, k) == v for k, v in fields.items()]
    )
    total_result = await session.exec(select(1).select_from(total_stmt.subquery()))
    total = total_result.scalar() or 0

    # Get paginated details
    stmt = select(ReportDetail).where(
        *[getattr(ReportDetail, k) == v for k, v in fields.items()]
    )

    # Apply ordering
    if params.order_by.startswith("-"):
        stmt = stmt.order_by(getattr(ReportDetail, params.order_by[1:]).desc())
    else:
        stmt = stmt.order_by(getattr(ReportDetail, params.order_by))

    # Apply pagination
    stmt = stmt.offset((params.page - 1) * params.perPage).limit(params.perPage)

    details_result = await session.exec(stmt)
    details = details_result.all()

    return ReportDetailsPublic(
        items=[detail for detail in details],
        total=total,
        page=params.page,
        perPage=params.perPage,
    )


@router.get("/{report_id}/download")
async def download_report(
    report_id: int, session: SessionDep, current_user: CurrentUserDep
):
    """Download a generated report file."""
    report_service = ReportService(session)
    report = await report_service.get_by_id(report_id)

    if not report:
        raise NotFoundException(f"Report with ID {report_id} not found")

    if not report.file_path:
        raise NotFoundException("Report file not generated yet")

    if not os.path.exists(report.file_path):
        raise NotFoundException("Report file not found on server")

    # Get filename from path
    filename = os.path.basename(report.file_path)

    return FileResponse(report.file_path, filename=filename, media_type="text/csv")


@router.get("/types", response_model=list[str])
async def get_report_types():
    """Get available report types."""
    from gpustack.schemas.reports import ReportTypeEnum

    return [t.value for t in ReportTypeEnum]
