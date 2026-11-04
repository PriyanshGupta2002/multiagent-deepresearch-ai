from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

ResearchDepth = Literal[
    "quick",
    "standard",
    "comprehensive",
]


ResearchStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
]


class ResearchCreateRequest(BaseModel):
    query: str = Field(
        min_length=5,
        max_length=5000,
    )

    depth: ResearchDepth = "standard"


class ResearchResponse(BaseModel):
    id: str
    query: str
    depth: ResearchDepth
    status: ResearchStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResearchTaskResponse(BaseModel):
    id: str
    title: str
    description: str | None
    status: str
    result: str | None
    error: str | None

    model_config = ConfigDict(from_attributes=True)


class ResearchReportResponse(BaseModel):
    id: str
    research_id: str
    content: str
    structured_content: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResearchSourceResponse(BaseModel):
    id: str
    url: str
    title: str | None
    snippet: str | None
    source_metadata: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResearchListResponse(BaseModel):
    items: list[ResearchResponse]
    total: int
    page: int
    limit: int
    total_pages: int
    has_more: bool
