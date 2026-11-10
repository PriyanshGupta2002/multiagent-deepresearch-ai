from fastapi import status, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal
from app.core.exceptions import AppException
from app.modules.research.models import (
    ResearchJob,
    utc_now,
    ResearchReport,
    ResearchSource,
)
from app.modules.conversations.models import ResearchConversation, ResearchMessage
from app.modules.conversations.schemas import ConversationCreate, MessageCreate
from app.agents.chat import stream_chat_response
import re
from datetime import datetime, timezone
from collections.abc import AsyncGenerator
import logging
from langchain_core.messages import AIMessage, HumanMessage

logger = logging.getLogger(__name__)


async def create_conversation(
    db: AsyncSession,
    user_id: str,
    data: ConversationCreate,
) -> ResearchConversation:

    # 1. Validate scope and research_id
    if data.scope == "research":
        if not data.research_id:
            raise AppException(
                message="Research ID is required for research conversations",
                error_code="RESEARCH_ID_REQUIRED",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # 2. Verify research ownership
        result = await db.execute(
            select(ResearchJob).where(
                ResearchJob.id == data.research_id,
                ResearchJob.user_id == user_id,
            )
        )

        research = result.scalar_one_or_none()

        if research is None:
            raise AppException(
                message="Research not found",
                error_code="RESEARCH_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    elif data.scope == "workspace":
        if data.research_id is not None:
            raise AppException(
                message="Workspace conversations cannot have a research ID",
                error_code="INVALID_WORKSPACE_RESEARCH_ID",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    # 3. Create conversation
    conversation = ResearchConversation(
        user_id=user_id,
        scope=data.scope,
        research_id=data.research_id,
        title=data.title,
    )

    # 4. Save to database
    db.add(conversation)

    try:
        await db.commit()
        await db.refresh(conversation)
    except Exception:
        await db.rollback()
        raise

    # 5. Return created conversation
    return conversation


async def get_conversation(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
) -> ResearchConversation:

    result = await db.execute(
        select(ResearchConversation).where(
            ResearchConversation.id == conversation_id,
            ResearchConversation.user_id == user_id,
        )
    )

    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise AppException(
            message="Conversation not found",
            error_code="CONVERSATION_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return conversation


async def list_conversations(
    db: AsyncSession,
    user_id: str,
    scope: Literal["research", "workspace"] | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict:

    # Base filter
    filters = [ResearchConversation.user_id == user_id]

    if scope is not None:
        filters.append(ResearchConversation.scope == scope)

    # Total conversations count
    count_query = select(func.count()).select_from(ResearchConversation).where(*filters)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Calculate pagination internally
    offset = (page - 1) * limit

    # Fetch conversations
    query = (
        select(ResearchConversation)
        .where(*filters)
        .order_by(
            ResearchConversation.updated_at.desc(),
            ResearchConversation.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    conversations = list(result.scalars().all())

    # Check if another page exists
    has_next = (page * limit) < total

    return {
        "items": conversations,
        "total": total,
        "page": page,
        "limit": limit,
        "has_next": has_next,
    }


async def get_messages(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
) -> list[ResearchMessage]:

    # Verify conversation ownership
    await get_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    # Fetch messages in chronological order
    query = (
        select(ResearchMessage)
        .where(ResearchMessage.conversation_id == conversation_id)
        .order_by(
            ResearchMessage.created_at.asc(),
            ResearchMessage.id.asc(),
        )
    )

    result = await db.execute(query)

    return list(result.scalars().all())


async def add_user_message(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    data: MessageCreate,
) -> ResearchMessage:

    # 1. Verify conversation ownership
    conversation = await get_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    # 2. Create user message
    message = ResearchMessage(
        conversation_id=conversation_id,
        role="user",
        content=data.content,
        citations=None,
        message_metadata=None,
    )

    # 3. Update conversation activity
    conversation.updated_at = utc_now()

    # 4. Save to database
    db.add(message)

    try:
        await db.commit()
        await db.refresh(message)
    except Exception:
        await db.rollback()
        raise

    return message


async def add_assistant_message(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    content: str,
    citations: list[dict] | None = None,
    message_metadata: dict | None = None,
) -> ResearchMessage:

    # 1. Verify conversation ownership
    conversation = await get_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    # 2. Create assistant message
    message = ResearchMessage(
        conversation_id=conversation_id,
        role="assistant",
        content=content,
        citations=citations,
        message_metadata=message_metadata,
    )

    # 3. Update conversation activity
    conversation.updated_at = utc_now()

    # 4. Save to database
    db.add(message)

    try:
        await db.commit()
        await db.refresh(message)
    except Exception:
        await db.rollback()
        raise

    return message


async def update_assistant_message(
    db: AsyncSession,
    conversation_id: str,
    message_id: str,
    user_id: str,
    content: str,
    citations: list[dict] | None = None,
    message_metadata: dict | None = None,
) -> ResearchMessage:

    # 1. Verify conversation ownership.
    conversation = await get_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    # 2. Fetch a fresh assistant message.
    message = await db.scalar(
        select(ResearchMessage).where(
            ResearchMessage.id == message_id,
            ResearchMessage.conversation_id == conversation_id,
            ResearchMessage.role == "assistant",
        )
    )

    if message is None:
        raise AppException(
            message="Assistant message not found",
            error_code="MESSAGE_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 3. Update existing message.
    message.content = content
    message.citations = citations
    message.message_metadata = message_metadata

    # 4. Update conversation activity.
    conversation.updated_at = utc_now()

    # 5. Commit changes.
    try:
        await db.commit()
        await db.refresh(message)

    except Exception:
        await db.rollback()
        raise

    return message


def build_chat_history(messages):
    chat_history = []

    for message in messages:
        if message.role == "user":
            chat_history.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            chat_history.append(AIMessage(content=message.content))

    return chat_history


async def build_research_context(db, conversation):
    if conversation.scope == "research":
        research_ids = [conversation.research_id]

    else:
        result = await db.execute(
            select(ResearchJob.id)
            .where(
                ResearchJob.user_id == conversation.user_id,
                ResearchJob.status == "completed",
            )
            .order_by(
                ResearchJob.created_at.desc(),
                ResearchJob.id.desc(),
            )
            .limit(5)
        )
        research_ids = list(result.scalars().all())

    if not research_ids:
        return "No completed research reports available.", {}

    report_result = await db.execute(
        select(ResearchJob, ResearchReport)
        .join(
            ResearchReport,
            ResearchReport.research_id == ResearchJob.id,
        )
        .where(
            ResearchJob.id.in_(research_ids),
            ResearchJob.user_id == conversation.user_id,
            ResearchJob.status == "completed",
        )
        .order_by(
            ResearchJob.created_at.desc(),
            ResearchJob.id.desc(),
        )
    )

    reports = report_result.all()
    report_research_ids = [job.id for job, _ in reports]

    if not report_research_ids:
        return "No completed research reports available.", []

    source_result = await db.execute(
        select(ResearchSource)
        .where(ResearchSource.research_id.in_(report_research_ids))
        .order_by(
            ResearchSource.created_at.asc(),
            ResearchSource.id.asc(),
        )
    )

    sources = source_result.scalars().all()

    if not reports:
        return "No completed research reports available.", {}

    # Only retrieve sources belonging to reports actually found above.
    available_research_ids = [job.id for job, report in reports]

    source_result = await db.execute(
        select(ResearchSource)
        .where(ResearchSource.research_id.in_(available_research_ids))
        .order_by(
            ResearchSource.created_at.asc(),
            ResearchSource.id.asc(),
        )
    )

    sources = source_result.scalars().all()

    citation_map = {}
    source_context = []

    for number, source in enumerate(sources, start=1):
        citation_map[number] = {
            "number": number,
            "source_id": source.id,
            "research_id": source.research_id,
            "title": source.title,
            "url": source.url,
        }

        source_context.append(f"""
[Source {number}]
Citation marker: [{number}]
Title: {source.title or "Untitled source"}
URL: {source.url or "Not available"}
Snippet: {source.snippet or "Not available"}
""")

    report_context = []

    for job, report in reports:
        report_context.append(f"""
Research Question: {job.query}

Report:
{report.content}
""")

    context = (
        "\n\n".join(report_context)
        + "\n\nAvailable Sources:\n"
        + "\n".join(source_context)
    )

    return context, citation_map


def extract_valid_citations(
    citation_numbers: list[int],
    citation_map: dict[int, dict],
) -> list[dict]:

    valid_numbers = set(citation_numbers)

    return [
        citation_map[number]
        for number in sorted(valid_numbers)
        if number in citation_map
    ]


async def stream_conversation_response(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    content: str,
) -> AsyncGenerator[dict, None]:

    try:
        # 1. Verify conversation ownership.
        conversation = await get_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )

        # 2. Load previous messages before saving current message.
        messages = await get_messages(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )

        chat_history = build_chat_history(messages)

        # 3. Retrieve report context and available source map.
        research_context, available_citations = await build_research_context(
            db,
            conversation,
        )

        # End the read transaction before generation.
        await db.rollback()

        # 4. Persist user message.
        user_message = await add_user_message(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            data=MessageCreate(content=content),
        )

        yield {
            "event": "message_start",
            "data": {
                "user_message_id": user_message.id,
            },
        }

        full_response = ""
        generation_metadata = {}
        model_citations = []
        suggested_questions = []

        # 5. Stream structured model response.
        async for item in stream_chat_response(
            question=content,
            research_context=research_context,
            chat_history=chat_history,
        ):

            if item["type"] == "token":
                delta = item["content"]
                full_response += delta

                yield {
                    "event": "token",
                    "data": {
                        "content": delta,
                    },
                }

            elif item["type"] == "structured_result":
                model_citations = item["citations"]
                suggested_questions = item["suggested_questions"]

            elif item["type"] == "generation_metadata":
                generation_metadata = item

        if not full_response.strip():
            raise ValueError("The model returned an empty answer.")

        # 6. Validate citations against retrieved database sources.
        citations = extract_valid_citations(
            citation_numbers=model_citations,
            citation_map=available_citations,
        )

        # 7. Prepare persisted metadata.
        metadata = {
            "model": generation_metadata.get("model"),
            "usage": generation_metadata.get("usage"),
            "cost": generation_metadata.get("cost"),
            "cost_details": generation_metadata.get("cost_details"),
            "suggested_questions": suggested_questions,
        }

        # 8. Persist completed assistant response.
        assistant_message = await add_assistant_message(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            content=full_response,
            citations=citations,
            message_metadata=metadata,
        )

        # 9. Send citations after persistence.
        yield {
            "event": "citations",
            "data": {
                "items": citations,
            },
        }

        if metadata["usage"] is not None:
            yield {
                "event": "usage",
                "data": metadata["usage"],
            }

        yield {
            "event": "cost",
            "data": {
                "amount": metadata["cost"],
                "details": metadata["cost_details"],
            },
        }

        yield {
            "event": "message_complete",
            "data": {
                "assistant_message_id": assistant_message.id,
                "status": "completed",
            },
        }

    except Exception:
        logger.exception(
            "Conversation response generation failed. conversation_id=%s",
            conversation_id,
        )

        yield {
            "event": "error",
            "data": {
                "message": "Sorry, something went wrong while generating the response.",
            },
        }


async def update_message_feedback(
    db: AsyncSession,
    user_id: str,
    conversation_id: str,
    message_id: str,
    rating: Literal["positive", "negative"],
) -> ResearchMessage:

    result = await db.execute(
        select(ResearchConversation).where(
            ResearchConversation.id == conversation_id,
            ResearchConversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise AppException(
            message="Conversation not found",
            error_code="CONVERSATION_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    result = await db.execute(
        select(ResearchMessage).where(
            ResearchMessage.id == message_id,
            ResearchMessage.conversation_id == conversation_id,
        )
    )
    message = result.scalar_one_or_none()

    if message is None:
        raise AppException(
            message="Message not found",
            error_code="MESSAGE_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if message.role != "assistant":
        raise AppException(
            message="Feedback can only be submitted for assistant messages",
            error_code="INVALID_FEEDBACK_TARGET",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    metadata = dict(message.message_metadata or {})

    metadata["feedback"] = {
        "rating": rating,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    message.message_metadata = metadata

    await db.commit()
    await db.refresh(message)

    return message


async def regenerate_conversation_response(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    message_id: str,
) -> AsyncGenerator[dict, None]:

    try:
        # 1. Verify conversation ownership.
        conversation = await get_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )

        # 2. Load existing conversation messages.
        messages = await get_messages(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )

        # 3. Find the assistant message to regenerate.
        target_index = next(
            (
                index
                for index, message in enumerate(messages)
                if message.id == message_id
            ),
            None,
        )

        if target_index is None:
            raise AppException(
                message="Assistant message not found",
                error_code="MESSAGE_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        target_message = messages[target_index]

        if target_message.role != "assistant":
            raise AppException(
                message="Only assistant messages can be regenerated",
                error_code="INVALID_MESSAGE_ROLE",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # 4. Ensure this is the latest assistant response.
        if target_index != len(messages) - 1:
            raise AppException(
                message="Only the latest assistant response can be regenerated",
                error_code="MESSAGE_NOT_LATEST",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # 5. Get the original user prompt.
        if target_index == 0 or messages[target_index - 1].role != "user":
            raise AppException(
                message="Original user message not found",
                error_code="USER_MESSAGE_NOT_FOUND",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user_message = messages[target_index - 1]
        question = user_message.content

        # Save scalar ID before rollback expires ORM objects.
        target_message_id = target_message.id

        # 6. Build history without the prompt being regenerated
        # and its corresponding assistant response.
        chat_history = build_chat_history(messages[: target_index - 1])

        # 7. Retrieve research context and citations.
        research_context, available_citations = await build_research_context(
            db,
            conversation,
        )

        # Save conversation ID before rollback.
        conversation_id = conversation.id

        # End the read transaction.
        await db.rollback()

        yield {
            "event": "regeneration_start",
            "data": {
                "assistant_message_id": target_message_id,
            },
        }

        full_response = ""
        generation_metadata = {}
        model_citations = []
        suggested_questions = []

        # 8. Generate and stream the new response.
        async for item in stream_chat_response(
            question=question,
            research_context=research_context,
            chat_history=chat_history,
        ):

            if item["type"] == "token":
                delta = item["content"]
                full_response += delta

                yield {
                    "event": "token",
                    "data": {
                        "content": delta,
                    },
                }

            elif item["type"] == "structured_result":
                model_citations = item["citations"]
                suggested_questions = item["suggested_questions"]

            elif item["type"] == "generation_metadata":
                generation_metadata = item

        if not full_response.strip():
            raise ValueError("The model returned an empty answer.")

        # 9. Validate citations.
        citations = extract_valid_citations(
            citation_numbers=model_citations,
            citation_map=available_citations,
        )

        # 10. Prepare fresh metadata.
        metadata = {
            "model": generation_metadata.get("model"),
            "usage": generation_metadata.get("usage"),
            "cost": generation_metadata.get("cost"),
            "cost_details": generation_metadata.get("cost_details"),
            "suggested_questions": suggested_questions,
        }

        # 11. Update existing assistant message.
        # The helper fetches a fresh ORM instance.
        updated_message = await update_assistant_message(
            db=db,
            conversation_id=conversation_id,
            message_id=target_message_id,
            user_id=user_id,
            content=full_response,
            citations=citations,
            message_metadata=metadata,
        )

        # 12. Send completion events.
        yield {
            "event": "citations",
            "data": {
                "items": citations,
            },
        }

        if metadata["usage"] is not None:
            yield {
                "event": "usage",
                "data": metadata["usage"],
            }

        yield {
            "event": "cost",
            "data": {
                "amount": metadata["cost"],
                "details": metadata["cost_details"],
            },
        }

        yield {
            "event": "message_complete",
            "data": {
                "assistant_message_id": updated_message.id,
                "status": "completed",
                "regenerated": True,
            },
        }

    except AppException:
        raise

    except Exception:
        logger.exception(
            "Conversation response regeneration failed. "
            "conversation_id=%s message_id=%s",
            conversation_id,
            message_id,
        )

        yield {
            "event": "error",
            "data": {
                "message": (
                    "Sorry, something went wrong while " "regenerating the response."
                ),
            },
        }
