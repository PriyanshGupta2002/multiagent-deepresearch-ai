from typing import Literal, TypedDict

ResearchDepth = Literal[
    "quick",
    "standard",
    "comprehensive",
]


class ResearchDepthConfig(TypedDict):
    max_subtasks: int
    max_concurrent_researchers: int
    max_critic_iterations: int
    report_detail: str


RESEARCH_DEPTH_CONFIG: dict[ResearchDepth, ResearchDepthConfig] = {
    "quick": {
        "max_subtasks": 3,
        "max_concurrent_researchers": 2,
        "max_critic_iterations": 1,
        "report_detail": "concise",
    },
    "standard": {
        "max_subtasks": 6,
        "max_concurrent_researchers": 4,
        "max_critic_iterations": 2,
        "report_detail": "balanced",
    },
    "comprehensive": {
        "max_subtasks": 12,
        "max_concurrent_researchers": 6,
        "max_critic_iterations": 3,
        "report_detail": "detailed",
    },
}
