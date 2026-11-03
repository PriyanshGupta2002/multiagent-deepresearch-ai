from app.graph.state import ResearchState
from app.agents.supervisor import supervisor_chain


async def supervisor_node(state: ResearchState) -> dict:

    result = await supervisor_chain.ainvoke(
        {
            "user_topic": state["topic"],
            "depth": state["depth"],
            "max_tasks": state["max_subtasks"],
        }
    )
    tasks = result.tasks[: state["max_subtasks"]]

    return {"tasks": tasks}
