import re

from fastapi import status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.research.models import ResearchJob, ResearchReport
from app.modules.saved_reports.models import SavedReport

REPORT_PREVIEW_LENGTH = 240


def _saved_report_response(
    saved_report: SavedReport,
    research: ResearchJob,
    report: ResearchReport,
) -> dict:
    return {
        "id": saved_report.id,
        "research_id": research.id,
        "query": research.query,
        "depth": research.depth,
        "report_created_at": report.created_at,
        "saved_at": saved_report.created_at,
    }


async def save_report(
    db: AsyncSession,
    user_id: str,
    research_id: str,
) -> tuple[dict, bool]:
    research = await db.scalar(
        select(ResearchJob).where(
            ResearchJob.id == research_id,
            ResearchJob.user_id == user_id,
        )
    )
    if research is None:
        raise AppException(
            message="Research not found",
            error_code="RESEARCH_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if research.status != "completed":
        raise AppException(
            message="Research is not completed",
            error_code="RESEARCH_NOT_COMPLETED",
            status_code=status.HTTP_409_CONFLICT,
        )

    report = await db.scalar(
        select(ResearchReport).where(ResearchReport.research_id == research_id)
    )
    if report is None:
        raise AppException(
            message="Research report has not been generated",
            error_code="RESEARCH_REPORT_NOT_GENERATED",
            status_code=status.HTTP_409_CONFLICT,
        )

    saved_report = await db.scalar(
        select(SavedReport).where(
            SavedReport.user_id == user_id,
            SavedReport.research_id == research_id,
        )
    )
    if saved_report is not None:
        return _saved_report_response(saved_report, research, report), False

    saved_report = SavedReport(user_id=user_id, research_id=research_id)
    db.add(saved_report)
    try:
        await db.commit()
        await db.refresh(saved_report)
    except IntegrityError:
        await db.rollback()
        saved_report = await db.scalar(
            select(SavedReport).where(
                SavedReport.user_id == user_id,
                SavedReport.research_id == research_id,
            )
        )
        if saved_report is None:
            raise

        return _saved_report_response(saved_report, research, report), False

    return _saved_report_response(saved_report, research, report), True


def _report_preview(content: str) -> str:
    excerpt = re.sub(r"\s+", " ", content).strip()
    if len(excerpt) > REPORT_PREVIEW_LENGTH:
        return f"{excerpt[: REPORT_PREVIEW_LENGTH - 3].rstrip()}..."
    return excerpt


async def list_saved_reports(
    db: AsyncSession,
    user_id: str,
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    depth: str | None = None,
) -> dict:
    filters = [SavedReport.user_id == user_id]
    if search:
        escaped_search = (
            search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        filters.append(ResearchJob.query.ilike(f"%{escaped_search}%", escape="\\"))
    if depth:
        filters.append(ResearchJob.depth == depth)

    joined_query = (
        select(SavedReport, ResearchJob, ResearchReport)
        .join(ResearchJob, ResearchJob.id == SavedReport.research_id)
        .join(ResearchReport, ResearchReport.research_id == ResearchJob.id)
        .where(*filters)
    )
    result = await db.execute(
        joined_query
        .order_by(SavedReport.created_at.desc(), SavedReport.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )

    items = []
    for saved_report, research, report in result.all():
        items.append(
            {
                **_saved_report_response(saved_report, research, report),
                "report_preview": _report_preview(report.content),
            }
        )

    total = await db.scalar(
        select(func.count(SavedReport.id))
        .select_from(SavedReport)
        .join(ResearchJob, ResearchJob.id == SavedReport.research_id)
        .join(ResearchReport, ResearchReport.research_id == ResearchJob.id)
        .where(*filters)
    )
    total = total or 0

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
        "has_more": page * limit < total,
    }


async def get_saved_report_status(
    db: AsyncSession,
    user_id: str,
    research_id: str,
) -> dict:
    saved_id = await db.scalar(
        select(SavedReport.id).where(
            SavedReport.user_id == user_id,
            SavedReport.research_id == research_id,
        )
    )
    return {"research_id": research_id, "is_saved": saved_id is not None}


async def unsave_report(
    db: AsyncSession,
    user_id: str,
    research_id: str,
) -> dict:
    await db.execute(
        delete(SavedReport).where(
            SavedReport.user_id == user_id,
            SavedReport.research_id == research_id,
        )
    )
    await db.commit()
    return {
        "success": True,
        "research_id": research_id,
        "is_saved": False,
    }
