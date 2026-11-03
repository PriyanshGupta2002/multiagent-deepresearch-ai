from langchain_core.tools import tool
from tavily import TavilyClient
from dotenv import load_dotenv
import json

load_dotenv()  # Load environment variables from .env file
client = TavilyClient()


@tool
def web_search_tool(query: str) -> str:
    """
    Search the web for reliable and relevant information
    about a research topic.

    Use this tool whenever external facts, recent information,
    statistics, or supporting sources are required.
    """
    print(f"\n[TAVILY SEARCH] Query: {query}")

    response = client.search(query=query, max_results=5, search_depth="advanced")

    return json.dumps(response, indent=2)
