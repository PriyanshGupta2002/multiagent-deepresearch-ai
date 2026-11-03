from app.graph.state import ResearchInput
from app.agents.researcher import researcher_executor
from app.schemas.research import Researcher
from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.runnables import RunnableConfig


async def researcher_node(
    state: ResearchInput,
    config: RunnableConfig,
):

    agent_config = {
        **(config or {}),
        "recursion_limit": 50,
    }

    print("\n========== RESEARCHER DEBUG ==========")
    print("SUBTASK:", state["subtask"])
    print("RECURSION LIMIT:", agent_config["recursion_limit"])
    print("======================================\n")

    await adispatch_custom_event(
        "researcher_started",
        {
            "subtask": state["subtask"],
        },
        config=config,
    )
    try:

        result = await researcher_executor.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": f"""
    Research the following subtask:

    {state['subtask']}

    Previous research critic feedback:

    {state.get('critic_feedback', '')}

    Address the identified gaps and provide stronger
    supporting evidence where possible.
    """,
                    }
                ],
            },
            config=agent_config,
        )

        research = result["structured_response"]
        research_results = Researcher(
            research=research.research,
            findings=research.findings,
            sources=research.sources,
            limitations=research.limitations,
        )

        await adispatch_custom_event(
            "researcher_completed",
            {
                "subtask": state["subtask"],
                "source_count": len(research.sources),
            },
            config=config,
        )

        return {
            "research_results": [research_results],
            "completed_tasks": [state["subtask"]],
        }
    except Exception as e:
        error_message = str(e)

        print(f"\n[RESEARCHER FAILED] {state['subtask']}")
        print(f"ERROR: {error_message}")

        try:
            await adispatch_custom_event(
                "researcher_failed",
                {
                    "subtask": state["subtask"],
                    "error": error_message,
                },
                config=config,
            )
        except Exception as event_error:
            print(f"[EVENT ERROR] {event_error}")

        return {
            "research_results": [],
            "failed_tasks": [
                {
                    "subtask": state["subtask"],
                    "error": error_message,
                    "error_type": type(e).__name__,
                }
            ],
        }
