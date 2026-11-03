from app.graph.state import ResearchState
from app.agents.critic import critic_chain


async def critic_node(state: ResearchState):
    result = await critic_chain.ainvoke(
        {
            "topic": state["topic"],
            "aggregated_results": state["aggregated_results"].model_dump_json(),
        }
    )

    return {
        "critic_score": result.score,
        "critic_feedback": result.feedback,
        "critic_acceptable": result.is_acceptable,
        "missing_areas": result.missing_areas,
        "unsupported_claims": result.unsupported_claims,
        "improvement_suggestions": result.improvement_suggestions,
        "retry_tasks": result.retry_tasks,
    }
