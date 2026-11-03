from datetime import datetime, timezone
import json
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.research.models import ResearchJob
from app.modules.research.models import ResearchEvent
import time
from app.db.session import AsyncSessionLocal
from fastapi import Request

import asyncio


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
    skip: int = 0,
    limit: int = 20,
):
    result = await db.execute(
        select(ResearchJob)
        .where(ResearchJob.user_id == user_id)
        .order_by(desc(ResearchJob.created_at))
        .offset(skip)
        .limit(limit)
    )

    return result.scalars().all()


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
) -> ResearchJob:

    if research.status not in ["queued", "running"]:
        raise ValueError(f"Cannot cancel research with status: {research.status}")

    research.status = "cancelled"
    research.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(research)

    return research


async def persist_research_event(
    db: AsyncSession,
    research_id: str,
    event_type: str,
    payload: dict,
) -> ResearchEvent:
    # Get the latest sequence number for this research.
    result = await db.execute(
        select(func.coalesce(func.max(ResearchEvent.sequence), 0)).where(
            ResearchEvent.research_id == research_id
        )
    )
    last_sequence = result.scalar_one()

    # Ensure payload is JSON serializable.
    safe_payload = json.loads(json.dumps(payload, default=str))

    event = ResearchEvent(
        research_id=research_id,
        event_type=event_type,
        payload=safe_payload,
        sequence=last_sequence + 1,
    )

    db.add(event)

    try:
        await db.commit()
        await db.refresh(event)
    except Exception:
        await db.rollback()
        raise

    return event


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
