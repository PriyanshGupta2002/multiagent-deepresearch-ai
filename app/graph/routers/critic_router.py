from app.graph.state import ResearchState


def critic_router(state: ResearchState):

    if state["critic_acceptable"]:
        return "final_report"

    if state["retry_count"] >= state["max_critic_iterations"]:
        return "final_report"

    if not state["retry_tasks"]:
        return "final_report"

    return "retry_research"
