from typing import TypedDict, Annotated
from pydantic import BaseModel
from app.modules.research.schemas import ResearchDepth
from app.schemas.research import Researcher, AggregatedResult
import operator


class ResearchState(TypedDict):
    topic: str
    depth: ResearchDepth
    tasks: list[str]
    max_subtasks: int
    max_concurrent_researchers: int
    max_critic_iterations: int
    report_detail: str
    research_results: Annotated[list[Researcher], operator.add]
    completed_tasks: Annotated[list[str], operator.add]
    failed_tasks: Annotated[list[dict[str, str]], operator.add]
    aggregated_results: AggregatedResult | None
    critic_score: float
    critic_feedback: str
    critic_acceptable: bool
    missing_areas: list[str]
    unsupported_claims: list[str]
    improvement_suggestions: list[str]
    retry_tasks: list[str]
    retry_count: int
    final_research: str


class ResearchInput(TypedDict):
    subtask: str
    critic_feedback: str | None
    depth: ResearchDepth
    report_detail: str
