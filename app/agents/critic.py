from app.core.get_llm import get_llm
from app.prompts.critic import prompt
from app.schemas.critic import CriticResult
from app.graph.state import ResearchState

llm = get_llm()

critic_llm = llm.with_structured_output(CriticResult)
critic_chain = prompt | critic_llm
