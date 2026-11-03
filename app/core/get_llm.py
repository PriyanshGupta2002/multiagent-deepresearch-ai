from langchain_openrouter import ChatOpenRouter
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file


def get_llm(model_name: str = "gpt-4o-mini") -> ChatOpenRouter:
    """
    Returns a ChatOpenRouter instance configured for the supervisor agent.
    """
    return ChatOpenRouter(
        model=model_name,
    )
