from app.core.get_llm import get_llm
from app.prompts.final_report import prompt

llm = get_llm("anthropic/claude-haiku-5.5")


final_report_chain = prompt | llm
