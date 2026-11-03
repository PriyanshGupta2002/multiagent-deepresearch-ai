from langgraph.types import Send

from app.graph.state import ResearchState


def dispatch_researchers(state: ResearchState):

    return [
        Send(
            "researcher",
            {
                "subtask": task,
                "critic_feedback": state.get("critic_feedback", ""),
                "depth": state["depth"],
                "report_detail": state["report_detail"],
            },
        )
        for task in state["tasks"]
    ]
