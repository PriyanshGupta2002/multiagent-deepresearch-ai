from fastapi import APIRouter, Depends, status, Query, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AppException
from app.db.dependencies import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from fastapi.responses import StreamingResponse
from app.modules.research.schemas import (
    ResearchCreateRequest,
    ResearchResponse,
    ResearchTaskResponse,
    ResearchReportResponse,
    ResearchSourceResponse,
    ResearchListResponse,
)
from app.modules.research.services import (
    create_research,
    get_user_researches,
    get_research_by_id,
    cancel_research,
    research_event_stream,
    get_research_report,
    get_research_tasks,
    get_research_sources,
    mark_research_enqueue_failed,
)

router = APIRouter(
    prefix="/research",
    tags=["Research"],
)


@router.post(
    "",
    response_model=ResearchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_research(
    data: ResearchCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    research = await create_research(
        db=db,
        user_id=current_user.id,
        query=data.query,
        depth=data.depth,
    )

    try:
        job_id = f"research:{research.id}"
        await request.app.state.redis_pool.enqueue_job(
            "run_research", research.id, _queue_name="deepresearch", _job_id=job_id
        )

    except Exception as exc:
        # Avoid leaving a permanently queued job
        await mark_research_enqueue_failed(
            db=db,
            research=research,
            error="Failed to enqueue research job",
        )

        raise AppException(
            message="Research service is temporarily unavailable",
            error_code="RESEARCH_ENQUEUE_FAILED",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    return research


@router.get("", response_model=ResearchListResponse)
async def list_researches(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_user_researches(
        db=db,
        user_id=current_user.id,
        page=page,
        limit=limit,
    )


@router.get("/{research_id}", response_model=ResearchResponse)
async def get_research(
    research_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    research = await get_research_by_id(
        db=db,
        research_id=research_id,
        user_id=current_user.id,
    )

    if not research:
        raise AppException(
            message="Research not found",
            error_code="RESEARCH_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return research


@router.post("/{research_id}/cancel", response_model=ResearchResponse)
async def cancel_research_endpoint(
    research_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    research = await get_research_by_id(
        db=db,
        research_id=research_id,
        user_id=current_user.id,
    )

    if not research:
        raise AppException(
            message="Research not found",
            error_code="RESEARCH_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return await cancel_research(
        db=db,
        research=research,
        redis_pool=request.app.state.redis_pool,
    )


@router.get("/{research_id}/events")
async def stream_research_events(
    research_id: str,
    request: Request,
    last_event_id: str | None = Header(
        default=None,
        alias="Last-Event-ID",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Verify research ownership.
    research = await get_research_by_id(
        db=db,
        research_id=research_id,
        user_id=current_user.id,
    )

    if not research:
        raise AppException(
            message="Research not found",
            error_code="RESEARCH_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 2. Validate Last-Event-ID.
    try:
        last_sequence = int(last_event_id) if last_event_id else 0

        if last_sequence < 0:
            raise ValueError

    except ValueError:
        raise AppException(
            message="Invalid Last-Event-ID",
            error_code="INVALID_LAST_EVENT_ID",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 3. Return SSE stream.
    return StreamingResponse(
        research_event_stream(
            request=request,
            research_id=research_id,
            last_event_id=last_sequence,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{research_id}/report",
    response_model=ResearchReportResponse,
)
async def get_research_report_endpoint(
    research_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify research ownership
    research = await get_research_by_id(
        db=db,
        research_id=research_id,
        user_id=current_user.id,
    )

    if not research:
        raise AppException(
            message="Research not found",
            error_code="RESEARCH_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Fetch report
    report = await get_research_report(
        db=db,
        research_id=research_id,
    )

    if not report:
        raise AppException(
            message="Research report not found",
            error_code="RESEARCH_REPORT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return report


@router.get(
    "/{research_id}/tasks",
    response_model=list[ResearchTaskResponse],
)
async def get_research_tasks_endpoint(
    research_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    research = await get_research_by_id(
        db=db,
        research_id=research_id,
        user_id=current_user.id,
    )

    if not research:
        raise AppException(
            message="Research not found",
            error_code="RESEARCH_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return await get_research_tasks(
        db=db,
        research_id=research_id,
    )


@router.get(
    "/{research_id}/sources",
    response_model=list[ResearchSourceResponse],
)
async def get_research_sources_endpoint(
    research_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    research = await get_research_by_id(
        db=db,
        research_id=research_id,
        user_id=current_user.id,
    )

    if not research:
        raise AppException(
            message="Research not found",
            error_code="RESEARCH_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return await get_research_sources(
        db=db,
        research_id=research_id,
    )
