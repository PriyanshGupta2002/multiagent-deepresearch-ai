import time

from app.graph.state import ResearchState
from app.agents.final_report import final_report_chain


async def final_report_node(state: ResearchState):

    aggregated_results = state["aggregated_results"].model_dump_json(indent=2)

    print(f"[FINAL REPORT] Input size: " f"{len(aggregated_results)} characters")

    start_time = time.perf_counter()

    result = await final_report_chain.ainvoke(
        {
            "topic": state["topic"],
            "aggregated_results": aggregated_results,
            "critic_feedback": state["critic_feedback"],
            "report_detail": state["report_detail"],
        }
    )

    elapsed = time.perf_counter() - start_time

    print(f"[FINAL REPORT] Completed in {elapsed:.2f}s")

    return {"final_research": result.content}
