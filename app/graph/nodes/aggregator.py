import json
import time

from app.graph.state import ResearchState
from app.agents.aggregator import aggregator_chain


async def aggregator_node(state: ResearchState):

    research_results = state["research_results"]

    if not research_results:
        raise RuntimeError(
            "Research failed: no researcher returned successful results."
        )

    input_size = len(
        json.dumps(
            research_results,
            default=str,
            ensure_ascii=False,
        )
    )

    print(f"[AGGREGATOR] Input size: {input_size} characters")
    print(f"[AGGREGATOR] Researchers: {len(research_results)}")

    start_time = time.perf_counter()

    result = await aggregator_chain.ainvoke({"research_results": research_results})

    elapsed = time.perf_counter() - start_time

    print(f"[AGGREGATOR] Completed in {elapsed:.2f}s")

    return {"aggregated_results": result}
