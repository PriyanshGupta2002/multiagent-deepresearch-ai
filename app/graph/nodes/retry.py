from app.graph.state import ResearchState


async def retry_node(state: ResearchState):

    return {
        "retry_count": state["retry_count"] + 1,
        "aggregated_results": None,
    }
