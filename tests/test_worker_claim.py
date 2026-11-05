import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete

import app.worker as worker
from app.modules.auth.models import User
from app.modules.research.models import ResearchEvent, ResearchJob


@pytest.mark.asyncio
async def test_queued_job_is_claimed(
    test_engine,
    test_session_factory,
    monkeypatch,
):
    assert test_session_factory.kw["bind"] is test_engine

    user_id = str(uuid.uuid4())
    research_id = str(uuid.uuid4())
    graph_calls = 0
    graph_started = asyncio.Event()

    async def cancel_graph(*args, **kwargs):
        nonlocal graph_calls
        graph_calls += 1
        graph_started.set()
        await asyncio.Event().wait()
        yield  # Makes this an async generator

    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    monkeypatch.setattr(worker.research_graph, "astream_events", cancel_graph)

    try:
        async with test_session_factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    full_name="Worker claim test",
                    hashed_password="unused",
                )
            )
            session.add(
                ResearchJob(
                    id=research_id,
                    user_id=user_id,
                    query="Worker claim test",
                    status="queued",
                )
            )
            await session.commit()

        worker_task = asyncio.create_task(worker.run_research({}, research_id))
        await graph_started.wait()
        worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker_task

        assert graph_calls == 1

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            assert job is not None
            assert job.status == "running"
            assert job.started_at is not None
    finally:
        async with test_session_factory() as session:
            await session.execute(
                delete(ResearchEvent).where(ResearchEvent.research_id == research_id)
            )
            await session.execute(
                delete(ResearchJob).where(ResearchJob.id == research_id)
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


async def _assert_job_status_is_skipped(
    status,
    test_engine,
    test_session_factory,
    monkeypatch,
):
    assert test_session_factory.kw["bind"] is test_engine

    user_id = str(uuid.uuid4())
    research_id = str(uuid.uuid4())
    graph_mock = AsyncMock()
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    monkeypatch.setattr(worker.research_graph, "astream_events", graph_mock)

    try:
        async with test_session_factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    full_name="Worker claim test",
                    hashed_password="unused",
                )
            )
            session.add(
                ResearchJob(
                    id=research_id,
                    user_id=user_id,
                    query="Worker claim test",
                    status=status,
                )
            )
            await session.commit()

        assert await worker.run_research({}, research_id) == {"status": status}
        graph_mock.assert_not_called()

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            assert job is not None
            assert job.status == status
    finally:
        async with test_session_factory() as session:
            await session.execute(
                delete(ResearchEvent).where(ResearchEvent.research_id == research_id)
            )
            await session.execute(
                delete(ResearchJob).where(ResearchJob.id == research_id)
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_running_job_is_not_claimed_again(
    test_engine,
    test_session_factory,
    monkeypatch,
):
    await _assert_job_status_is_skipped(
        "running",
        test_engine,
        test_session_factory,
        monkeypatch,
    )


@pytest.mark.asyncio
async def test_completed_job_is_skipped(
    test_engine,
    test_session_factory,
    monkeypatch,
):
    await _assert_job_status_is_skipped(
        "completed",
        test_engine,
        test_session_factory,
        monkeypatch,
    )


@pytest.mark.asyncio
async def test_cancelled_job_is_skipped(
    test_engine,
    test_session_factory,
    monkeypatch,
):
    await _assert_job_status_is_skipped(
        "cancelled",
        test_engine,
        test_session_factory,
        monkeypatch,
    )


@pytest.mark.asyncio
async def test_missing_job_raises_error(test_engine, test_session_factory, monkeypatch):
    assert test_session_factory.kw["bind"] is test_engine

    graph_mock = AsyncMock()
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    monkeypatch.setattr(worker.research_graph, "astream_events", graph_mock)

    with pytest.raises(ValueError, match="Research job .* not found"):
        await worker.run_research({}, str(uuid.uuid4()))

    graph_mock.assert_not_called()
