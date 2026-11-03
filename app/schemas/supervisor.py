from pydantic import BaseModel, Field


class Supervisor(BaseModel):
    tasks: list[str] = Field(
        ...,
        min_length=3,
        max_length=5,
        description=(
            "3 to 5 independent, specific and actionable "
            "research tasks without overlapping."
        ),
    )
