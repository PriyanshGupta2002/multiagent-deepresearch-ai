from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessageChunk

from app.core.get_llm import get_llm
from app.modules.conversations.schemas import ChatAnswerOutput
from app.prompts.chat import chat_prompt

llm = get_llm(model_name="anthropic/claude-haiku-5.5")

structured_llm = llm.with_structured_output(
    ChatAnswerOutput,
    method="json_schema",
    strict=True,
    include_raw=True,
)

chat_chain = chat_prompt | structured_llm


def get_answer_text(parsed: Any) -> str:
    if parsed is None:
        return ""

    if isinstance(parsed, ChatAnswerOutput):
        return parsed.answer

    if isinstance(parsed, dict):
        return parsed.get("answer", "") or ""

    return ""


async def stream_chat_response(
    question: str,
    research_context: str,
    chat_history: list,
) -> AsyncGenerator[dict[str, Any], None]:

    final_raw = None
    final_parsed = None
    streamed_answer = ""

    inputs = {
        "question": question,
        "research_context": research_context,
        "chat_history": chat_history,
    }

    async for chunk in chat_chain.astream(inputs):

        raw_chunk = chunk.get("raw")
        parsed_chunk = chunk.get("parsed")
        parsing_error = chunk.get("parsing_error")

        if parsing_error is not None:
            raise ValueError(f"Structured output parsing failed: {parsing_error}")

        # Accumulate raw model chunks for usage and cost metadata.
        if isinstance(raw_chunk, AIMessageChunk):
            final_raw = raw_chunk if final_raw is None else final_raw + raw_chunk

        if parsed_chunk is not None:
            final_parsed = parsed_chunk

            current_answer = get_answer_text(parsed_chunk)

            # Stream only the newly generated answer text.
            if current_answer and current_answer.startswith(streamed_answer):
                delta = current_answer[len(streamed_answer) :]

                if delta:
                    streamed_answer = current_answer

                    yield {
                        "type": "token",
                        "content": delta,
                    }

    if final_parsed is None:
        raise ValueError("The model did not return a valid structured response.")

    # Validate the final structured response.
    if isinstance(final_parsed, ChatAnswerOutput):
        structured_result = final_parsed
    else:
        structured_result = ChatAnswerOutput.model_validate(final_parsed)

    final_answer = structured_result.answer.strip()

    if not final_answer:
        raise ValueError("The model returned an empty answer.")

    # Catch any final answer correction not emitted during streaming.
    final_answer = structured_result.answer

    if not final_answer.strip():
        raise ValueError("The model returned an empty answer.")

    if final_answer.startswith(streamed_answer):
        remaining = final_answer[len(streamed_answer) :]

        if remaining:
            yield {
                "type": "token",
                "content": remaining,
            }
    else:
        raise ValueError("Final structured answer differs from streamed answer.")

    usage = final_raw.usage_metadata if final_raw else None
    response_metadata = final_raw.response_metadata or {} if final_raw else {}

    yield {
        "type": "structured_result",
        "answer": final_answer,
        "citations": structured_result.citations,
        "suggested_questions": structured_result.suggested_questions,
    }

    yield {
        "type": "generation_metadata",
        "model": getattr(llm, "model", None),
        "usage": usage,
        "cost": response_metadata.get("cost"),
        "cost_details": response_metadata.get("cost_details"),
    }
