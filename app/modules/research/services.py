from datetime import datetime, timezone
import json
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.research.models import ResearchJob
from app.modules.research.models import ResearchEvent
import time
from app.db.session import AsyncSessionLocal
from fastapi import Request

import asyncio
from arq.jobs import Job, JobStatus
from app.modules.research.models import ResearchReport, ResearchTask, ResearchSource
from fastapi import status


async def mark_research_enqueue_failed(
    db: AsyncSession,
    research: ResearchJob,
    error: str,
) -> None:

    research.status = "failed"
    research.error = error
    research.completed_at = datetime.now(timezone.utc)

    result = await db.execute(
        select(func.coalesce(func.max(ResearchEvent.sequence), 0)).where(
            ResearchEvent.research_id == research.id
        )
    )

    next_sequence = result.scalar_one() + 1

    db.add(
        ResearchEvent(
            research_id=research.id,
            event_type="research_failed",
            payload={
                "status": "failed",
                "error": error,
            },
            sequence=next_sequence,
        )
    )

    await db.commit()


async def create_research(
    db: AsyncSession,
    user_id: str,
    query: str,
    depth: str,
) -> ResearchJob:

    research = ResearchJob(
        user_id=user_id,
        query=query,
        depth=depth,
        status="queued",
    )

    db.add(research)

    await db.commit()
    await db.refresh(research)

    return research


async def get_user_researches(
    db: AsyncSession,
    user_id: str,
    page: int = 1,
    limit: int = 20,
):
    skip = (page - 1) * limit

    result = await db.execute(
        select(ResearchJob)
        .where(ResearchJob.user_id == user_id)
        .order_by(desc(ResearchJob.created_at))
        .offset(skip)
        .limit(limit)
    )

    researches = result.scalars().all()

    count_result = await db.execute(
        select(func.count(ResearchJob.id)).where(ResearchJob.user_id == user_id)
    )

    total = count_result.scalar_one()

    return {
        "items": researches,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
        "has_more": page * limit < total,
    }


async def get_research_by_id(
    db: AsyncSession,
    research_id: str,
    user_id: str,
) -> ResearchJob | None:

    result = await db.execute(
        select(ResearchJob).where(
            ResearchJob.id == research_id,
            ResearchJob.user_id == user_id,
        )
    )

    return result.scalar_one_or_none()


async def cancel_research(
    db: AsyncSession,
    research: ResearchJob,
    redis_pool,
) -> ResearchJob:
    """
    Abort the ARQ job and persist the cancellation state and event.
    """

    # 1. Refresh research status
    await db.refresh(research)

    if research.status not in {"queued", "running"}:
        raise AppException(
            message=f"Cannot cancel research with status: {research.status}",
            error_code="RESEARCH_CANCELLATION_CONFLICT",
            status_code=status.HTTP_409_CONFLICT,
        )

    # 2. Identify the corresponding ARQ job
    job_id = f"research:{research.id}"

    arq_job = Job(
        job_id=job_id,
        redis=redis_pool,
        _queue_name="deepresearch",
    )

    # 3. Check current ARQ job status
    arq_status = await arq_job.status()

    if arq_status in {JobStatus.queued, JobStatus.deferred}:

        try:
            await arq_job.abort(
                timeout=2,
                poll_delay=0.2,
            )

        except asyncio.TimeoutError:
            # Abort request is registered in Redis.
            # Worker will process it when available.
            pass

    elif arq_status == JobStatus.in_progress:

        aborted = await arq_job.abort(
            timeout=10,
            poll_delay=0.2,
        )

        if not aborted:
            raise AppException(
                message="Could not abort the running research job.",
                error_code="RESEARCH_CANCELLATION_CONFLICT",
                status_code=status.HTTP_409_CONFLICT,
            )

    else:
        raise AppException(
            message=f"ARQ job cannot be cancelled. Current status: {arq_status}",
            error_code="RESEARCH_CANCELLATION_CONFLICT",
            status_code=status.HTTP_409_CONFLICT,
        )

    # 4. Lock research row and update database atomically
    try:
        result = await db.execute(
            select(ResearchJob).where(ResearchJob.id == research.id).with_for_update()
        )

        locked_research = result.scalar_one_or_none()

        if not locked_research:
            raise AppException(
                message="Research not found",
                error_code="RESEARCH_CANCELLATION_CONFLICT",
                status_code=status.HTTP_409_CONFLICT,
            )

        # Recheck status after acquiring the lock
        if locked_research.status not in {"queued", "running"}:
            raise AppException(
                message=f"Cannot cancel research with status: {locked_research.status}",
                error_code="RESEARCH_CANCELLATION_CONFLICT",
                status_code=status.HTTP_409_CONFLICT,
            )

        # Update research status
        locked_research.status = "cancelled"
        locked_research.completed_at = datetime.now(timezone.utc)

        # 5. Generate next event sequence
        result = await db.execute(
            select(func.coalesce(func.max(ResearchEvent.sequence), 0)).where(
                ResearchEvent.research_id == locked_research.id
            )
        )

        next_sequence = result.scalar_one() + 1

        # 6. Persist cancellation event
        cancellation_event = ResearchEvent(
            research_id=locked_research.id,
            event_type="research_cancelled",
            payload={
                "status": "cancelled",
                "message": "Research was cancelled by the user.",
            },
            sequence=next_sequence,
        )

        db.add(cancellation_event)

        # 7. Commit transaction
        await db.commit()
        await db.refresh(locked_research)

        return locked_research

    except Exception:
        await db.rollback()
        raise


async def persist_research_event(
    db: AsyncSession,
    research_id: str,
    event_type: str,
    payload: dict,
) -> ResearchEvent:

    try:
        # Lock the parent research row.
        # Concurrent event writers for the same research
        # must wait until the current transaction completes.
        result = await db.execute(
            select(ResearchJob).where(ResearchJob.id == research_id).with_for_update()
        )

        research = result.scalar_one_or_none()

        if not research:
            raise ValueError(f"Research not found: {research_id}")

        # Fetch the latest event sequence.
        result = await db.execute(
            select(func.coalesce(func.max(ResearchEvent.sequence), 0)).where(
                ResearchEvent.research_id == research_id
            )
        )

        last_sequence = result.scalar_one()

        # Ensure JSON serializable payload.
        safe_payload = json.loads(json.dumps(payload, default=str))

        event = ResearchEvent(
            research_id=research_id,
            event_type=event_type,
            payload=safe_payload,
            sequence=last_sequence + 1,
        )

        db.add(event)

        await db.commit()
        await db.refresh(event)

        return event

    except Exception:
        await db.rollback()
        raise


async def research_event_stream(
    request: Request,
    research_id: str,
    last_event_id: int = 0,
):
    poll_interval = 1
    heartbeat_interval = 15

    last_sequence = last_event_id
    last_heartbeat = time.monotonic()

    terminal_events = {
        "research_completed",
        "research_failed",
        "research_cancelled",
    }

    while True:

        # Stop if the client disconnects.
        if await request.is_disconnected():
            break

        async with AsyncSessionLocal() as db:

            # Fetch new events in sequence order.
            result = await db.execute(
                select(ResearchEvent)
                .where(
                    ResearchEvent.research_id == research_id,
                    ResearchEvent.sequence > last_sequence,
                )
                .order_by(ResearchEvent.sequence.asc())
            )

            events = result.scalars().all()

            # Read current research status.
            job = await db.get(ResearchJob, research_id)

            if not job:
                return

            research_status = job.status

            # Release database session before streaming.
            event_data = [
                {
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "payload": event.payload,
                }
                for event in events
            ]

        # Stream newly persisted events.
        for event in event_data:

            sequence = event["sequence"]
            event_type = event["event_type"]
            payload = event["payload"]

            message = (
                f"id: {sequence}\n"
                f"event: {event_type}\n"
                f"data: {json.dumps(payload, default=str)}\n\n"
            )

            yield message

            last_sequence = sequence
            last_heartbeat = time.monotonic()

            # Stop after terminal events.
            if event_type in terminal_events:
                return

        # Stop if the job is already terminal.
        if research_status in {
            "completed",
            "failed",
            "cancelled",
        }:
            yield (
                f"event: stream_end\n"
                f"data: {json.dumps({'status': research_status})}\n\n"
            )
            return

        # Send heartbeat to keep the connection alive.
        now = time.monotonic()

        if now - last_heartbeat >= heartbeat_interval:
            yield ": keep-alive\n\n"
            last_heartbeat = now

        await asyncio.sleep(poll_interval)


async def get_research_report(
    db: AsyncSession,
    research_id: str,
) -> ResearchReport | None:

    result = await db.execute(
        select(ResearchReport).where(ResearchReport.research_id == research_id)
    )

    return result.scalar_one_or_none()


async def get_research_tasks(
    db: AsyncSession,
    research_id: str,
) -> list[ResearchTask]:

    result = await db.execute(
        select(ResearchTask)
        .where(ResearchTask.research_id == research_id)
        .order_by(ResearchTask.created_at.asc())
    )

    return list(result.scalars().all())


async def get_research_sources(
    db: AsyncSession,
    research_id: str,
) -> list[ResearchSource]:

    result = await db.execute(
        select(ResearchSource)
        .where(ResearchSource.research_id == research_id)
        .order_by(ResearchSource.created_at.asc())
    )

    return list(result.scalars().all())
