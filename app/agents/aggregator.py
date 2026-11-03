from app.core.get_llm import get_llm
from app.prompts.aggregator import prompt
from app.schemas.research import AggregatedResult

llm = get_llm("anthropic/claude-haiku-5.5")

aggregator_llm = llm.with_structured_output(AggregatedResult)


aggregator_chain = (prompt | aggregator_llm).with_retry(
    stop_after_attempt=2,
    wait_exponential_jitter=True,
)
