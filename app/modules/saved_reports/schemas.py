from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.research.schemas import ResearchDepth


class SaveReportRequest(BaseModel):
    research_id: UUID


class SavedReportResponse(BaseModel):
    id: str
    research_id: str
    query: str
    depth: ResearchDepth
    report_created_at: datetime
    saved_at: datetime


class SavedReportListItem(SavedReportResponse):
    report_preview: str


class SavedReportListResponse(BaseModel):
    items: list[SavedReportListItem]
    total: int
    page: int
    limit: int
    total_pages: int
    has_more: bool


class SavedReportStatusResponse(BaseModel):
    research_id: str
    is_saved: bool


class UnsaveReportResponse(SavedReportStatusResponse):
    success: Literal[True] = True
