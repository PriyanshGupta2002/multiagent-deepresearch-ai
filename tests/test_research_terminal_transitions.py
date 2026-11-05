import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

import app.modules.research.services as research_services
import app.worker as worker
from app.core.exceptions import AppException
from app.modules.research.services import ResearchJobNotRunning
from app.modules.auth.models import User
from app.modules.research.models import (
    ResearchEvent,
    ResearchJob,
    ResearchReport,
    ResearchSource,
    ResearchTask,
)


async def _create_running_job(test_session_factory):
    return await _create_job(test_session_factory, "running")


async def _create_job(test_session_factory, status):
    user_id = str(uuid.uuid4())
    research_id = str(uuid.uuid4())

    async with test_session_factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"{user_id}@example.test",
                full_name="Terminal transition test",
                hashed_password="unused",
            )
        )
        session.add(
            ResearchJob(
                id=research_id,
                user_id=user_id,
                query="Terminal transition test",
                status=status,
            )
        )
        await session.commit()

    return user_id, research_id


async def _delete_test_records(test_session_factory, user_id, research_id):
    async with test_session_factory() as session:
        await session.execute(
            delete(ResearchEvent).where(ResearchEvent.research_id == research_id)
        )
        await session.execute(
            delete(ResearchReport).where(ResearchReport.research_id == research_id)
        )
        await session.execute(
            delete(ResearchSource).where(ResearchSource.research_id == research_id)
        )
        await session.execute(
            delete(ResearchTask).where(ResearchTask.research_id == research_id)
        )
        await session.execute(
            delete(ResearchJob).where(ResearchJob.id == research_id)
        )
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


def _completion_data():
    return {
        "final_research": "Completed report",
        "retry_count": 0,
        "critic_score": 1.0,
    }, {"report": "structured"}, SimpleNamespace(sources=[])


async def _cancel_job(test_session_factory, research_id, monkeypatch):
    class FakeJob:
        def __init__(self, **kwargs):
            pass

        async def abort(self, **kwargs):
            return True

    monkeypatch.setattr(research_services, "Job", FakeJob)
    async with test_session_factory() as session:
        research = await session.get(ResearchJob, research_id)
        assert research is not None
        await research_services.cancel_research(session, research, redis_pool=None)


@pytest.mark.asyncio
async def test_cancellation_wins_over_completion(test_session_factory, monkeypatch):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_running_job(test_session_factory)
    abort_started = asyncio.Event()
    allow_abort_to_finish = asyncio.Event()

    class FakeJob:
        def __init__(self, **kwargs):
            pass

        async def abort(self, **kwargs):
            async with test_session_factory() as session:
                job = await session.get(ResearchJob, research_id)
                events = (
                    await session.scalars(
                        select(ResearchEvent).where(
                            ResearchEvent.research_id == research_id
                        )
                    )
                ).all()
                assert job is not None
                assert job.status == "cancelled"
                assert [event.event_type for event in events] == [
                    "research_cancelled"
                ]

            abort_started.set()
            await allow_abort_to_finish.wait()
            raise asyncio.TimeoutError

    monkeypatch.setattr(research_services, "Job", FakeJob)

    async def cancel():
        async with test_session_factory() as session:
            research = await session.get(ResearchJob, research_id)
            assert research is not None
            return await research_services.cancel_research(
                session,
                research,
                redis_pool=None,
            )

    cancel_task = asyncio.create_task(cancel())
    try:
        await abort_started.wait()

        final_state, structured_content, aggregated = _completion_data()
        terminal_status = await worker._finalize_research(
            research_id,
            final_state,
            structured_content,
            aggregated,
        )
        assert terminal_status == "cancelled"

        allow_abort_to_finish.set()
        cancelled_job = await cancel_task
        assert cancelled_job.status == "cancelled"

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id
                    )
                )
            ).all()
            report = await session.scalar(
                select(ResearchReport).where(
                    ResearchReport.research_id == research_id
                )
            )
            sources = (
                await session.scalars(
                    select(ResearchSource).where(
                        ResearchSource.research_id == research_id
                    )
                )
            ).all()

            assert job is not None
            assert job.status == "cancelled"
            assert [event.event_type for event in events] == ["research_cancelled"]
            assert report is None
            assert sources == []
    finally:
        allow_abort_to_finish.set()
        if not cancel_task.done():
            await cancel_task
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_completion_wins_over_cancellation(test_session_factory, monkeypatch):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_running_job(test_session_factory)
    try:
        async with test_session_factory() as session:
            research = await session.get(ResearchJob, research_id)
            assert research is not None
            await session.close()

        final_state, structured_content, aggregated = _completion_data()
        assert (
            await worker._finalize_research(
                research_id,
                final_state,
                structured_content,
                aggregated,
            )
            == "completed"
        )

        async with test_session_factory() as session:
            session.add(research)
            with pytest.raises(AppException) as exc_info:
                await research_services.cancel_research(
                    session,
                    research,
                    redis_pool=None,
                )
            assert exc_info.value.status_code == 409

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id
                    )
                )
            ).all()
            report = await session.scalar(
                select(ResearchReport).where(
                    ResearchReport.research_id == research_id
                )
            )

            assert job is not None
            assert job.status == "completed"
            assert [event.event_type for event in events] == [
                "research_completed"
            ]
            assert report is not None
            assert report.content == "Completed report"
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_worker_failure_wins_before_cancellation(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_job(test_session_factory, "queued")

    async def fail_graph(*args, **kwargs):
        raise RuntimeError("graph failed")
        yield

    monkeypatch.setattr(worker.research_graph, "astream_events", fail_graph)

    try:
        with pytest.raises(RuntimeError, match="graph failed"):
            await worker.run_research({}, research_id)

        async with test_session_factory() as session:
            research = await session.get(ResearchJob, research_id)
            assert research is not None
            with pytest.raises(AppException) as exc_info:
                await research_services.cancel_research(
                    session,
                    research,
                    redis_pool=None,
                )
            assert exc_info.value.status_code == 409

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id,
                        ResearchEvent.event_type.in_(
                            [
                                "research_completed",
                                "research_failed",
                                "research_cancelled",
                            ]
                        ),
                    )
                )
            ).all()

            assert job is not None
            assert job.status == "failed"
            assert job.error == "graph failed"
            assert [event.event_type for event in events] == ["research_failed"]
            assert events[0].payload == {
                "status": "failed",
                "error": "graph failed",
            }
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "abort_error",
    [asyncio.TimeoutError(), RuntimeError("ARQ unavailable")],
)
async def test_cancellation_wins_before_worker_failure(
    test_session_factory,
    monkeypatch,
    abort_error,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_job(test_session_factory, "queued")
    graph_started = asyncio.Event()
    allow_graph_to_fail = asyncio.Event()
    graph_stopped = asyncio.Event()
    cancellation_committed = asyncio.Event()

    async def blocked_graph(*args, **kwargs):
        graph_started.set()
        try:
            await allow_graph_to_fail.wait()
        finally:
            graph_stopped.set()
        yield

    class FakeJob:
        def __init__(self, **kwargs):
            pass

        async def abort(self, **kwargs):
            async with test_session_factory() as session:
                job = await session.get(ResearchJob, research_id)
                events = (
                    await session.scalars(
                        select(ResearchEvent).where(
                            ResearchEvent.research_id == research_id
                        ).order_by(ResearchEvent.sequence)
                    )
                ).all()
                assert job is not None
                assert job.status == "cancelled"
                assert [event.event_type for event in events] == [
                    "research_started",
                    "research_cancelled",
                ]

            cancellation_committed.set()
            raise abort_error

    async def read_status(_research_id):
        await cancellation_committed.wait()
        return "cancelled"

    monkeypatch.setattr(worker.research_graph, "astream_events", blocked_graph)
    monkeypatch.setattr(worker, "_read_research_status", read_status)
    monkeypatch.setattr(research_services, "Job", FakeJob)

    async def cancel():
        async with test_session_factory() as session:
            research = await session.get(ResearchJob, research_id)
            assert research is not None
            return await research_services.cancel_research(
                session,
                research,
                redis_pool=None,
            )

    worker_task = asyncio.create_task(worker.run_research({}, research_id))
    cancel_task = None
    try:
        await graph_started.wait()
        cancel_task = asyncio.create_task(cancel())
        await cancellation_committed.wait()

        assert await worker_task == {
            "status": "cancelled",
            "research_id": research_id,
        }
        assert graph_stopped.is_set()
        cancelled_job = await cancel_task
        assert cancelled_job.status == "cancelled"

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id,
                        ResearchEvent.event_type.in_(
                            [
                                "research_completed",
                                "research_failed",
                                "research_cancelled",
                            ]
                        ),
                    )
                )
            ).all()

            assert job is not None
            assert job.status == "cancelled"
            assert [event.event_type for event in events] == ["research_cancelled"]
    finally:
        allow_graph_to_fail.set()
        if not worker_task.done():
            await worker_task
        if cancel_task is not None and not cancel_task.done():
            await cancel_task
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_enqueue_failure_marks_queued_job_failed(test_session_factory):
    user_id, research_id = await _create_job(test_session_factory, "queued")
    try:
        async with test_session_factory() as session:
            research = await session.get(ResearchJob, research_id)
            assert research is not None

        async with test_session_factory() as session:
            session.add(research)
            await research_services.mark_research_enqueue_failed(
                session,
                research,
                "Failed to enqueue research job",
            )

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id,
                        ResearchEvent.event_type.in_(
                            [
                                "research_completed",
                                "research_failed",
                                "research_cancelled",
                            ]
                        ),
                    )
                )
            ).all()

            assert job is not None
            assert job.status == "failed"
            assert job.error == "Failed to enqueue research job"
            assert [event.event_type for event in events] == ["research_failed"]
            assert events[0].payload == {
                "status": "failed",
                "error": "Failed to enqueue research job",
            }
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_enqueue_failure_does_not_override_cancellation(
    test_session_factory,
    monkeypatch,
):
    user_id, research_id = await _create_job(test_session_factory, "queued")

    class FakeJob:
        def __init__(self, **kwargs):
            pass

        async def abort(self, **kwargs):
            return True

    monkeypatch.setattr(research_services, "Job", FakeJob)

    try:
        async with test_session_factory() as session:
            stale_research = await session.get(ResearchJob, research_id)
            assert stale_research is not None

        async with test_session_factory() as session:
            research = await session.get(ResearchJob, research_id)
            assert research is not None
            await research_services.cancel_research(
                session,
                research,
                redis_pool=None,
            )

        async with test_session_factory() as session:
            session.add(stale_research)
            await research_services.mark_research_enqueue_failed(
                session,
                stale_research,
                "Failed to enqueue research job",
            )

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id,
                        ResearchEvent.event_type.in_(
                            [
                                "research_completed",
                                "research_failed",
                                "research_cancelled",
                            ]
                        ),
                    )
                )
            ).all()

            assert job is not None
            assert job.status == "cancelled"
            assert [event.event_type for event in events] == ["research_cancelled"]
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_progress_event_after_cancellation_is_rejected(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_running_job(test_session_factory)

    try:
        await _cancel_job(test_session_factory, research_id, monkeypatch)

        with pytest.raises(ResearchJobNotRunning) as exc_info:
            await worker.save_research_event(
                research_id,
                "supervisor_started",
                {},
            )
        assert exc_info.value.status == "cancelled"

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id
                    )
                )
            ).all()
            assert job is not None
            assert job.status == "cancelled"
            assert [event.event_type for event in events] == ["research_cancelled"]
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_task_creation_after_cancellation_is_rejected(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_running_job(test_session_factory)

    try:
        await _cancel_job(test_session_factory, research_id, monkeypatch)

        with pytest.raises(ResearchJobNotRunning) as exc_info:
            await worker.persist_generated_tasks(research_id, ["late task"])
        assert exc_info.value.status == "cancelled"

        async with test_session_factory() as session:
            tasks = (
                await session.scalars(
                    select(ResearchTask).where(
                        ResearchTask.research_id == research_id
                    )
                )
            ).all()
            assert tasks == []
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_task_update_after_cancellation_is_rejected(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_running_job(test_session_factory)
    async with test_session_factory() as session:
        task = ResearchTask(
            research_id=research_id,
            title="existing task",
            description="existing task",
            status="running",
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    try:
        await _cancel_job(test_session_factory, research_id, monkeypatch)

        with pytest.raises(ResearchJobNotRunning) as exc_info:
            await worker.update_research_task(
                research_id,
                "existing task",
                "completed",
            )
        assert exc_info.value.status == "cancelled"

        async with test_session_factory() as session:
            task = await session.get(ResearchTask, task_id)
            assert task is not None
            assert task.status == "running"
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_running_job_accepts_progress_events_and_task_writes(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_running_job(test_session_factory)

    try:
        await worker.save_research_event(research_id, "research_started", {})
        await worker.save_research_event(research_id, "supervisor_started", {})
        await worker.persist_generated_tasks(research_id, ["first task"])
        await worker.update_research_task(
            research_id,
            "first task",
            "completed",
        )

        async with test_session_factory() as session:
            events = (
                await session.scalars(
                    select(ResearchEvent)
                    .where(ResearchEvent.research_id == research_id)
                    .order_by(ResearchEvent.sequence)
                )
            ).all()
            tasks = (
                await session.scalars(
                    select(ResearchTask).where(
                        ResearchTask.research_id == research_id
                    )
                )
            ).all()

            assert [event.event_type for event in events] == [
                "research_started",
                "supervisor_started",
            ]
            assert [event.sequence for event in events] == [1, 2]
            assert len(tasks) == 1
            assert tasks[0].status == "completed"
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_worker_stops_when_progress_guard_detects_cancellation(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_job(test_session_factory, "queued")

    async def cancel_then_yield(*args, **kwargs):
        await _cancel_job(test_session_factory, research_id, monkeypatch)
        yield {
            "event": "on_custom_event",
            "name": "researcher_started",
            "data": {"subtask": "late task"},
        }

    monkeypatch.setattr(worker.research_graph, "astream_events", cancel_then_yield)

    try:
        result = await worker.run_research({}, research_id)
        assert result == {"status": "cancelled", "research_id": research_id}

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id
                    )
                )
            ).all()
            tasks = (
                await session.scalars(
                    select(ResearchTask).where(
                        ResearchTask.research_id == research_id
                    )
                )
            ).all()

            assert job is not None
            assert job.status == "cancelled"
            assert [event.event_type for event in events] == [
                "research_started",
                "research_cancelled",
            ]
            assert tasks == []
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_terminal_status_watcher_uses_a_mocked_status_read(monkeypatch):
    status_reads = []

    async def read_status(research_id):
        status_reads.append(research_id)
        return "cancelled"

    monkeypatch.setattr(worker, "_read_research_status", read_status)

    assert await worker._wait_for_terminal_research_status("watcher-test") == "cancelled"
    assert status_reads == ["watcher-test"]


@pytest.mark.asyncio
async def test_queued_cancellation_is_skipped_by_worker(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_job(test_session_factory, "queued")
    abort_calls = 0

    class FakeJob:
        def __init__(self, **kwargs):
            pass

        async def abort(self, **kwargs):
            nonlocal abort_calls
            abort_calls += 1
            return True

    monkeypatch.setattr(research_services, "Job", FakeJob)
    graph_mock = AsyncMock()
    monkeypatch.setattr(worker.research_graph, "astream_events", graph_mock)

    try:
        async with test_session_factory() as session:
            research = await session.get(ResearchJob, research_id)
            assert research is not None
            await research_services.cancel_research(session, research, redis_pool=None)

        assert await worker.run_research({}, research_id) == {"status": "cancelled"}
        graph_mock.assert_not_called()
        assert abort_calls == 1

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id
                    )
                )
            ).all()
            assert job is not None
            assert job.status == "cancelled"
            assert [event.event_type for event in events] == ["research_cancelled"]
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_repeated_cancellation_retries_abort_without_duplicate_event(
    test_session_factory,
    monkeypatch,
):
    user_id, research_id = await _create_running_job(test_session_factory)
    abort_calls = 0

    class FakeJob:
        def __init__(self, **kwargs):
            pass

        async def abort(self, **kwargs):
            nonlocal abort_calls
            abort_calls += 1
            async with test_session_factory() as session:
                job = await session.get(ResearchJob, research_id)
                events = (
                    await session.scalars(
                        select(ResearchEvent).where(
                            ResearchEvent.research_id == research_id
                        )
                    )
                ).all()
                assert job is not None
                assert job.status == "cancelled"
                assert [event.event_type for event in events] == [
                    "research_cancelled"
                ]
            return True

    monkeypatch.setattr(research_services, "Job", FakeJob)

    try:
        async with test_session_factory() as session:
            research = await session.get(ResearchJob, research_id)
            assert research is not None
            await research_services.cancel_research(session, research, redis_pool=None)

        async with test_session_factory() as session:
            research = await session.get(ResearchJob, research_id)
            assert research is not None
            with pytest.raises(AppException) as exc_info:
                await research_services.cancel_research(
                    session,
                    research,
                    redis_pool=None,
                )
            assert exc_info.value.status_code == 409

        assert abort_calls == 2
        async with test_session_factory() as session:
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id
                    )
                )
            ).all()
            assert [event.event_type for event in events] == ["research_cancelled"]
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_external_arq_cancellation_cleans_up_graph_and_watcher(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_job(test_session_factory, "queued")
    graph_started = asyncio.Event()
    graph_stopped = asyncio.Event()
    watcher_started = asyncio.Event()
    watcher_stopped = asyncio.Event()

    async def blocked_graph(*args, **kwargs):
        graph_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            graph_stopped.set()
        yield

    async def blocked_status_read(_research_id):
        watcher_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            watcher_stopped.set()

    monkeypatch.setattr(worker.research_graph, "astream_events", blocked_graph)
    monkeypatch.setattr(worker, "_read_research_status", blocked_status_read)

    try:
        task = asyncio.create_task(worker.run_research({}, research_id))
        await graph_started.wait()
        await watcher_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert graph_stopped.is_set()
        assert watcher_stopped.is_set()
        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            terminal_events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id,
                        ResearchEvent.event_type.in_(
                            [
                                "research_completed",
                                "research_failed",
                                "research_cancelled",
                            ]
                        ),
                    )
                )
            ).all()
            assert job is not None
            assert job.status == "running"
            assert terminal_events == []
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_cancellation_after_graph_completion_wins_at_finalizer(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_job(test_session_factory, "queued")
    graph_finished = asyncio.Event()
    finalizer_entered = asyncio.Event()
    allow_finalizer = asyncio.Event()
    original_finalizer = worker._finalize_research

    final_state = {
        "final_research": "Completed report",
        "retry_count": 0,
        "critic_score": 1.0,
        "critic_feedback": "",
        "aggregated_results": SimpleNamespace(sources=[]),
    }

    async def completed_graph(*args, **kwargs):
        try:
            yield {
                "event": "on_chain_end",
                "data": {"output": final_state},
                "parent_ids": [],
            }
        finally:
            graph_finished.set()

    async def blocked_finalizer(*args, **kwargs):
        finalizer_entered.set()
        await allow_finalizer.wait()
        return await original_finalizer(*args, **kwargs)

    class FakeJob:
        def __init__(self, **kwargs):
            pass

        async def abort(self, **kwargs):
            return True

    monkeypatch.setattr(worker.research_graph, "astream_events", completed_graph)
    monkeypatch.setattr(worker, "_finalize_research", blocked_finalizer)
    monkeypatch.setattr(research_services, "Job", FakeJob)

    worker_task = asyncio.create_task(worker.run_research({}, research_id))
    cancel_task = None
    try:
        await finalizer_entered.wait()
        assert graph_finished.is_set()

        async def cancel():
            async with test_session_factory() as session:
                research = await session.get(ResearchJob, research_id)
                assert research is not None
                return await research_services.cancel_research(
                    session,
                    research,
                    redis_pool=None,
                )

        cancel_task = asyncio.create_task(cancel())
        cancelled_job = await cancel_task
        assert cancelled_job.status == "cancelled"
        allow_finalizer.set()

        assert await worker_task == {
            "status": "cancelled",
            "research_id": research_id,
        }

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id,
                        ResearchEvent.event_type.in_(
                            [
                                "research_completed",
                                "research_failed",
                                "research_cancelled",
                            ]
                        ),
                    )
                )
            ).all()
            report = await session.scalar(
                select(ResearchReport).where(
                    ResearchReport.research_id == research_id
                )
            )
            assert job is not None
            assert job.status == "cancelled"
            assert [event.event_type for event in events] == ["research_cancelled"]
            assert report is None
    finally:
        allow_finalizer.set()
        if not worker_task.done():
            await worker_task
        if cancel_task is not None and not cancel_task.done():
            await cancel_task
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
async def test_independent_graph_child_cancellation_is_not_an_arq_abort(
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_job(test_session_factory, "queued")

    async def independently_cancelled_graph(*args, **kwargs):
        raise asyncio.CancelledError
        yield

    monkeypatch.setattr(
        worker.research_graph,
        "astream_events",
        independently_cancelled_graph,
    )

    try:
        with pytest.raises(RuntimeError, match="cancelled unexpectedly"):
            await worker.run_research({}, research_id)

        async with test_session_factory() as session:
            job = await session.get(ResearchJob, research_id)
            events = (
                await session.scalars(
                    select(ResearchEvent).where(
                        ResearchEvent.research_id == research_id,
                        ResearchEvent.event_type.in_(
                            [
                                "research_completed",
                                "research_failed",
                                "research_cancelled",
                            ]
                        ),
                    )
                )
            ).all()
            assert job is not None
            assert job.status == "failed"
            assert [event.event_type for event in events] == ["research_failed"]
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["graph", "parent"])
async def test_iterator_close_failure_does_not_mask_original_error(
    test_session_factory,
    monkeypatch,
    caplog,
    failure_mode,
):
    monkeypatch.setattr(worker, "AsyncSessionLocal", test_session_factory)
    user_id, research_id = await _create_job(test_session_factory, "queued")
    graph_started = asyncio.Event()
    iterator_closed = asyncio.Event()

    class GraphIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            graph_started.set()
            if failure_mode == "graph":
                raise ValueError("original graph error")
            await asyncio.Event().wait()

        async def aclose(self):
            iterator_closed.set()
            raise RuntimeError("iterator close error")

    monkeypatch.setattr(
        worker.research_graph,
        "astream_events",
        lambda *args, **kwargs: GraphIterator(),
    )

    try:
        if failure_mode == "graph":
            with pytest.raises(ValueError, match="original graph error"):
                await worker.run_research({}, research_id)
        else:
            task = asyncio.create_task(worker.run_research({}, research_id))
            await graph_started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert iterator_closed.is_set()
        assert "Failed to close research graph iterator" in caplog.text
        assert "iterator close error" in caplog.text
    finally:
        await _delete_test_records(test_session_factory, user_id, research_id)
