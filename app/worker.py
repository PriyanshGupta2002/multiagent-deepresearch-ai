from datetime import datetime, timezone

from arq.connections import RedisSettings
from app.modules.research.services import (
    ResearchJobNotRunning,
    lock_running_research_job,
    persist_research_event,
)
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.modules.auth.models import User

from app.modules.research.models import (
    ResearchJob,
    ResearchReport,
    ResearchSource,
    ResearchEvent,
    ResearchTask,
)


from app.modules.research.constants import RESEARCH_DEPTH_CONFIG

from app.graph.workflow import research_graph

from sqlalchemy import select, func, update

from app.modules.research.models import ResearchTask

import asyncio
import logging

logger = logging.getLogger(__name__)

RESEARCH_STATUS_POLL_INTERVAL = 0.25


async def health_check(ctx):
    return {
        "status": "worker_running",
        "message": "ARQ worker is ready",
    }


async def _read_research_status(research_id: str) -> str:
    async with AsyncSessionLocal() as db:
        status_value = await db.scalar(
            select(ResearchJob.status).where(ResearchJob.id == research_id)
        )

    if status_value is None:
        raise ValueError(f"Research job {research_id} not found")

    return status_value


async def _wait_for_terminal_research_status(research_id: str) -> str:
    while True:
        status_value = await _read_research_status(research_id)
        if status_value != "running":
            return status_value

        await asyncio.sleep(RESEARCH_STATUS_POLL_INTERVAL)


async def save_research_event(
    research_id: str,
    event_type: str,
    payload: dict | None = None,
):
    async with AsyncSessionLocal() as db:
        await persist_research_event(
            db=db,
            research_id=research_id,
            event_type=event_type,
            payload=payload or {},
        )


async def persist_generated_tasks(
    research_id: str,
    tasks: list[str],
):
    async with AsyncSessionLocal() as db:
        await lock_running_research_job(db, research_id)

        for task in tasks:
            db.add(
                ResearchTask(
                    research_id=research_id,
                    title=task,
                    description=task,
                    status="pending",
                )
            )

        await db.commit()


async def update_research_task(
    research_id: str,
    subtask: str,
    status: str,
    error: str | None = None,
):
    async with AsyncSessionLocal() as db:
        await lock_running_research_job(db, research_id)

        # Find the latest matching task that has not finished.
        result = await db.execute(
            select(ResearchTask)
            .where(
                ResearchTask.research_id == research_id,
                ResearchTask.title == subtask,
                ResearchTask.status.in_(["pending", "running"]),
            )
            .order_by(ResearchTask.created_at.desc())
            .limit(1)
        )

        task = result.scalar_one_or_none()

        # A retry can create a new attempt for an already
        # completed or failed task.
        if task is None and status == "running":
            task = ResearchTask(
                research_id=research_id,
                title=subtask,
                description=subtask,
                status="running",
            )
            db.add(task)

        if task:
            task.status = status
            task.error = error

        await db.commit()


async def _finalize_research(
    research_id: str,
    final_state: dict,
    structured_content: dict,
    aggregated,
) -> str:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResearchJob)
            .where(ResearchJob.id == research_id)
            .with_for_update()
        )
        job = result.scalar_one_or_none()

        if not job:
            raise ValueError(f"Research job {research_id} not found")

        if job.status != "running":
            current_status = job.status
            await db.rollback()
            logger.info(
                "Not completing research %s because its status is %s",
                research_id,
                current_status,
            )
            return current_status

        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)

        db.add(
            ResearchReport(
                research_id=research_id,
                content=final_state["final_research"],
                structured_content=structured_content,
            )
        )

        seen_urls = set()
        for source in aggregated.sources:
            if source.url in seen_urls:
                continue

            seen_urls.add(source.url)
            db.add(
                ResearchSource(
                    research_id=research_id,
                    url=source.url,
                    title=source.title,
                    source_metadata={"published_date": source.published_date},
                )
            )

        result = await db.execute(
            select(func.coalesce(func.max(ResearchEvent.sequence), 0)).where(
                ResearchEvent.research_id == research_id
            )
        )
        next_sequence = result.scalar_one() + 1

        db.add(
            ResearchEvent(
                research_id=research_id,
                event_type="research_completed",
                payload={
                    "status": "completed",
                    "retry_count": final_state["retry_count"],
                    "critic_score": final_state["critic_score"],
                },
                sequence=next_sequence,
            )
        )

        await db.commit()
        return "completed"


async def _mark_research_failed(research_id: str, error: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResearchJob)
            .where(ResearchJob.id == research_id)
            .with_for_update()
        )
        job = result.scalar_one_or_none()

        if job is None or job.status != "running":
            await db.rollback()
            return False

        job.status = "failed"
        job.error = error
        job.completed_at = datetime.now(timezone.utc)

        result = await db.execute(
            select(func.coalesce(func.max(ResearchEvent.sequence), 0)).where(
                ResearchEvent.research_id == research_id
            )
        )
        next_sequence = result.scalar_one() + 1

        db.add(
            ResearchEvent(
                research_id=research_id,
                event_type="research_failed",
                payload={"status": "failed", "error": error},
                sequence=next_sequence,
            )
        )

        await db.commit()
        return True


async def run_research(ctx, research_id: str):

    # 1. Atomically claim the queued research job.
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(ResearchJob)
            .where(
                ResearchJob.id == research_id,
                ResearchJob.status == "queued",
            )
            .values(
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            .returning(ResearchJob.query, ResearchJob.depth)
        )
        claimed_job = result.one_or_none()

        if claimed_job is None:
            job_status = await db.scalar(
                select(ResearchJob.status).where(ResearchJob.id == research_id)
            )
            if job_status is None:
                raise ValueError(f"Research job {research_id} not found")

            await db.rollback()
            logger.info(
                "Skipping research job %s because its status is %s",
                research_id,
                job_status,
            )
            return {"status": job_status}

        query, depth = claimed_job

        # Commit the claim before starting graph execution.
        await db.commit()

    try:
        # 2. Load depth configuration
        depth_config = RESEARCH_DEPTH_CONFIG[depth]

        # 3. Build initial graph state
        initial_state = {
            "topic": query,
            "depth": depth,
            **depth_config,
            "tasks": [],
            "research_results": [],
            "completed_tasks": [],
            "failed_tasks": [],
            "aggregated_results": None,
            "critic_score": 0.0,
            "critic_feedback": "",
            "critic_acceptable": False,
            "missing_areas": [],
            "unsupported_claims": [],
            "improvement_suggestions": [],
            "retry_tasks": [],
            "retry_count": 0,
            "final_research": "",
        }

        # 4. Configure LangGraph concurrency
        graph_config = {
            "recursion_limit": 50,
            "max_concurrency": depth_config["max_concurrent_researchers"],
        }

        print(
            f"Starting research: {research_id} | "
            f"Depth: {depth} | "
            f"Concurrency: {graph_config['max_concurrency']}"
        )

        await save_research_event(
            research_id,
            "research_started",
            {
                "query": query,
                "depth": depth,
            },
        )

        # 5. Execute research graph
        final_state = None

        graph_events = research_graph.astream_events(
            initial_state,
            version="v2",
            config=graph_config,
        )
        event_task = asyncio.create_task(anext(graph_events))
        watcher_task = asyncio.create_task(
            _wait_for_terminal_research_status(research_id)
        )

        try:
            while True:
                done, _ = await asyncio.wait(
                    {event_task, watcher_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if event_task in done:
                    try:
                        event = event_task.result()
                    except StopAsyncIteration:
                        break
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                        if watcher_task.done():
                            return {
                                "status": watcher_task.result(),
                                "research_id": research_id,
                            }
                        status_value = await _read_research_status(research_id)
                        if status_value != "running":
                            return {
                                "status": status_value,
                                "research_id": research_id,
                            }
                        raise RuntimeError(
                            f"Research graph task for {research_id} was "
                            "cancelled unexpectedly."
                        )
                    except Exception:
                        if watcher_task.done():
                            return {
                                "status": watcher_task.result(),
                                "research_id": research_id,
                            }
                        raise

                else:
                    terminal_status = watcher_task.result()

                    # The graph may have completed between wait() returning
                    # and this check. Let its output reach the DB finalizer.
                    if event_task.done():
                        continue

                    event_task.cancel()
                    try:
                        await event_task
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise

                    return {
                        "status": terminal_status,
                        "research_id": research_id,
                    }

                event_name = event.get("event")
                node_name = event.get("name")
                event_data = event.get("data", {})
                metadata = event.get("metadata", {})

                # ------------------------------------------
                # A. Custom researcher events
                # ------------------------------------------

                if event_name == "on_custom_event":
                    custom_name = node_name
                    payload = event_data if isinstance(event_data, dict) else {}

                    subtask = payload.get("subtask")

                    if custom_name == "researcher_started":
                        await update_research_task(
                            research_id=research_id,
                            subtask=subtask,
                            status="running",
                        )

                    elif custom_name == "researcher_completed":
                        await update_research_task(
                            research_id=research_id,
                            subtask=subtask,
                            status="completed",
                        )

                    elif custom_name == "researcher_failed":
                        await update_research_task(
                            research_id=research_id,
                            subtask=subtask,
                            status="failed",
                            error=payload.get("error"),
                        )

                    await save_research_event(
                        research_id,
                        custom_name,
                        payload,
                    )

                    print(f"[EVENT SAVED] {custom_name}")

                    event_task = asyncio.create_task(anext(graph_events))
                    continue

                # ------------------------------------------
                # B. Actual LangGraph node lifecycle events
                # ------------------------------------------

                graph_node = metadata.get("langgraph_node")

                tracked_nodes = {
                    "supervisor",
                    "aggregator",
                    "critic",
                    "retry",
                    "final_report",
                }

                if graph_node in tracked_nodes and node_name == graph_node:

                    if event_name == "on_chain_start":
                        await save_research_event(
                            research_id,
                            f"{graph_node}_started",
                            {},
                        )

                        print(f"[NODE STARTED] {graph_node}")

                    elif event_name == "on_chain_end":
                        output = event_data.get("output", {})

                        if not isinstance(output, dict):
                            output = {}

                        # Supervisor: persist generated tasks
                        if graph_node == "supervisor":
                            tasks = output.get("tasks", [])

                            if tasks:
                                await persist_generated_tasks(
                                    research_id=research_id,
                                    tasks=tasks,
                                )

                                await save_research_event(
                                    research_id,
                                    "tasks_generated",
                                    {
                                        "tasks": tasks,
                                        "total_tasks": len(tasks),
                                    },
                                )

                                print(f"[TASKS SAVED] {len(tasks)} tasks")

                        # Aggregator completed
                        elif graph_node == "aggregator":
                            await save_research_event(
                                research_id,
                                "aggregator_completed",
                                {},
                            )

                        # Critic completed
                        elif graph_node == "critic":
                            await save_research_event(
                                research_id,
                                "critic_completed",
                                {
                                    "critic_score": output.get("critic_score"),
                                    "critic_acceptable": output.get("critic_acceptable"),
                                    "critic_feedback": output.get("critic_feedback"),
                                    "retry_tasks": output.get("retry_tasks", []),
                                },
                            )

                        # Retry completed
                        elif graph_node == "retry":
                            await save_research_event(
                                research_id,
                                "retry_completed",
                                {
                                    "retry_count": output.get("retry_count"),
                                    "retry_tasks": output.get("retry_tasks", []),
                                },
                            )

                        # Final report completed
                        elif graph_node == "final_report":
                            await save_research_event(
                                research_id,
                                "final_report_completed",
                                {
                                    "report_generated": bool(output.get("final_research")),
                                },
                            )

                        print(f"[NODE COMPLETED] {graph_node}")

                # ------------------------------------------
                # C. Capture root graph output
                # ------------------------------------------

                if event_name == "on_chain_end" and not event.get("parent_ids"):
                    final_state = event_data.get("output")

                event_task = asyncio.create_task(anext(graph_events))
        finally:
            if not watcher_task.done():
                watcher_task.cancel()
            if not event_task.done():
                event_task.cancel()
            await asyncio.gather(
                watcher_task,
                event_task,
                return_exceptions=True,
            )
            close_graph_events = getattr(graph_events, "aclose", None)
            if close_graph_events is not None:
                try:
                    await close_graph_events()
                except (Exception, asyncio.CancelledError):
                    logger.exception(
                        "Failed to close research graph iterator for %s.",
                        research_id,
                    )

        # ----------------------------------------------
        # 6. Validate final graph output
        # ----------------------------------------------

        if not final_state:
            raise RuntimeError("Research graph returned no final state")

        if not final_state.get("final_research"):
            raise RuntimeError("Final research report is empty")

        # ----------------------------------------------
        # 7. Prepare report data
        # ----------------------------------------------

        aggregated = final_state["aggregated_results"]

        if hasattr(aggregated, "model_dump"):
            structured_content = aggregated.model_dump(mode="json")
        else:
            structured_content = aggregated

        structured_content = {
            "aggregated_results": structured_content,
            "critic_score": final_state["critic_score"],
            "critic_feedback": final_state["critic_feedback"],
            "retry_count": final_state["retry_count"],
        }

        # ----------------------------------------------
        # 8. Persist report, sources, job and completion
        #    event in one transaction
        # ----------------------------------------------

        terminal_status = await _finalize_research(
            research_id=research_id,
            final_state=final_state,
            structured_content=structured_content,
            aggregated=aggregated,
        )

        if terminal_status != "completed":
            return {"status": terminal_status, "research_id": research_id}

        print(f"[RESEARCH COMPLETED] {research_id}")

        return {
            "status": "completed",
            "research_id": research_id,
        }

    except asyncio.CancelledError:
        logger.info(
            "Research %s was cancelled by ARQ",
            research_id,
        )
        raise
    except ResearchJobNotRunning as exc:
        logger.info(
            "Stopping research %s because its status is %s",
            research_id,
            exc.status,
        )
        return {"status": exc.status, "research_id": research_id}
    except Exception as e:
        await _mark_research_failed(research_id, str(e))

        print(f"[RESEARCH FAILED] {research_id}: {e}")

        raise


class WorkerSettings:

    functions = [
        health_check,
        run_research,
    ]

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    queue_name = "deepresearch"
    max_jobs = 5
    job_timeout = 3600
    max_tries = 1
    allow_abort_jobs = True
