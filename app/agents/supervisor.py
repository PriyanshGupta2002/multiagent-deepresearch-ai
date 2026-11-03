from app.core.get_llm import get_llm
from app.schemas.supervisor import Supervisor
from app.prompts.supervisor import prompt

llm = get_llm("qwen/qwen3.8-27b")

supervisor_llm = llm.with_structured_output(Supervisor)

supervisor_chain = prompt | supervisor_llm
