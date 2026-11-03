from fastapi import APIRouter, Depends, HTTPException, status, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request
from app.db.dependencies import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from fastapi.responses import StreamingResponse
from app.modules.research.schemas import (
    ResearchCreateRequest,
    ResearchResponse,
)
from app.modules.research.services import (
    create_research,
    get_user_researches,
    get_research_by_id,
    cancel_research,
    research_event_stream,
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
        await request.app.state.redis_pool.enqueue_job(
            "run_research",
            research.id,
            _queue_name="deepresearch",
        )

    except Exception:
        # Avoid leaving a permanently queued job
        research.status = "failed"
        research.error = "Failed to enqueue research job"
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research service is temporarily unavailable",
        )

    return research


@router.get("", response_model=list[ResearchResponse])
async def list_researches(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_user_researches(
        db=db,
        user_id=current_user.id,
        skip=skip,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research not found",
        )

    return research


@router.post("/{research_id}/cancel", response_model=ResearchResponse)
async def cancel_research_endpoint(
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research not found",
        )

    try:
        return await cancel_research(db, research)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research not found",
        )

    # 2. Validate Last-Event-ID.
    try:
        last_sequence = int(last_event_id) if last_event_id else 0

        if last_sequence < 0:
            raise ValueError

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Last-Event-ID",
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
