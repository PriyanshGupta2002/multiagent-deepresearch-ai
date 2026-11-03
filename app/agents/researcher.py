from typing import TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ToolCallLimitMiddleware,
    ModelCallLimitMiddleware,
)

from app.core.get_llm import get_llm
from app.prompts.research import RESEARCHER_SYSTEM_PROMPT
from app.schemas.research import Researcher

from app.tools.search import web_search_tool
from app.tools.skills import (
    load_base_skill,
    load_research_skill,
)

# Load mandatory base skill
base_skill = load_base_skill()

system_prompt = f"""
{RESEARCHER_SYSTEM_PROMPT}

# Mandatory Base Research Skill

{base_skill}
"""


llm = get_llm("google/gemini-3.8-flash")


researcher_executor = create_agent(
    model=llm,
    tools=[
        web_search_tool,
        load_research_skill,
    ],
    system_prompt=system_prompt,
    response_format=Researcher,
    middleware=[
        ToolCallLimitMiddleware(
            run_limit=5,
            exit_behavior="end",
        ),
        ModelCallLimitMiddleware(
            run_limit=8,
            exit_behavior="end",
        ),
    ],
)
