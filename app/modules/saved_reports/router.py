from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.dependencies import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.saved_reports.schemas import (
    SaveReportRequest,
    SavedReportListResponse,
    SavedReportStatusResponse,
    SavedReportResponse,
    UnsaveReportResponse,
)
from app.modules.saved_reports.services import (
    get_saved_report_status,
    list_saved_reports,
    save_report,
    unsave_report,
)

router = APIRouter(
    prefix="/saved-reports",
    tags=["Saved Reports"],
)


@router.post(
    "",
    response_model=SavedReportResponse,
)
async def save_report_endpoint(
    data: SaveReportRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result, created = await save_report(
        db=db,
        user_id=current_user.id,
        research_id=str(data.research_id),
    )
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return result


@router.get("", response_model=SavedReportListResponse)
async def list_saved_reports_endpoint(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None, max_length=500),
    depth: str | None = Query(
        default=None,
        pattern="^(quick|standard|comprehensive)$",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_saved_reports(
        db=db,
        user_id=current_user.id,
        page=page,
        limit=limit,
        search=search,
        depth=depth,
    )


@router.get(
    "/{research_id}/status",
    response_model=SavedReportStatusResponse,
)
async def saved_report_status_endpoint(
    research_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_saved_report_status(
        db=db,
        user_id=current_user.id,
        research_id=str(research_id),
    )


@router.delete(
    "/{research_id}",
    response_model=UnsaveReportResponse,
)
async def unsave_report_endpoint(
    research_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await unsave_report(
        db=db,
        user_id=current_user.id,
        research_id=str(research_id),
    )
