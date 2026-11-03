from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    title: str
    url: str
    published_date: str | None = None


class ResearchFinding(BaseModel):
    claim: str = Field(
        description="A specific factual claim discovered during research."
    )

    explanation: str = Field(
        description="Detailed explanation and supporting evidence for the claim."
    )

    supporting_sources: list[str] = Field(
        description="URLs from the research sources that support this claim."
    )


class Researcher(BaseModel):
    research: str = Field(
        description="Comprehensive research summary for the assigned subtask."
    )

    findings: list[ResearchFinding] = Field(
        description="Individual evidence-backed findings."
    )

    sources: list[SourceReference] = Field(
        description="Sources actually retrieved and used during research."
    )

    limitations: list[str] = Field(
        description="Evidence gaps, uncertainties and research limitations."
    )


class AggregatedResult(BaseModel):

    research: str = Field(description="Comprehensive combined research report.")

    findings: list[ResearchFinding] = Field(
        description="Consolidated and deduplicated research findings."
    )

    sources: list[SourceReference] = Field(
        description="Unique sources used across all researchers."
    )

    conflicting_evidence: list[str] = Field(
        description="Claims where researchers found conflicting evidence."
    )

    research_gaps: list[str] = Field(
        description="Important unanswered questions or missing evidence."
    )
