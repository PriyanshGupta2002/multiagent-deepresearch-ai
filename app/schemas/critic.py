from pydantic import BaseModel, Field


class CriticResult(BaseModel):

    score: float = Field(
        ge=0, le=10, description="Overall research quality score from 0 to 10."
    )

    is_acceptable: bool = Field(
        description="Whether the research meets the required quality standards."
    )

    feedback: str = Field(
        description="Detailed explanation of the research quality and issues."
    )

    missing_areas: list[str] = Field(
        description="Important topics or aspects missing from the research."
    )

    unsupported_claims: list[str] = Field(
        description="Claims that lack sufficient supporting evidence."
    )

    improvement_suggestions: list[str] = Field(
        description="Specific suggestions to improve research quality."
    )

    retry_tasks: list[str] = Field(
        description="Specific research tasks that should be investigated again."
    )
