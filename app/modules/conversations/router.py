from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User

from app.modules.conversations import services
from app.modules.conversations.schemas import (
    ConversationCreate,
    ConversationResponse,
    ConversationListResponse,
    MessageResponse,
    MessageFeedbackCreate,
    MessageFeedbackResponse,
)
from collections.abc import AsyncGenerator

from fastapi.responses import StreamingResponse
from app.modules.conversations.schemas import MessageCreate
import json

router = APIRouter(
    prefix="/conversations",
    tags=["Conversations"],
)


def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\n" f"data: {json.dumps(data, default=str)}\n\n"


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await services.create_conversation(
        db=db,
        user_id=current_user.id,
        data=data,
    )


@router.get(
    "",
    response_model=ConversationListResponse,
)
async def list_conversations(
    scope: Literal["research", "workspace"] | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await services.list_conversations(
        db=db,
        user_id=current_user.id,
        scope=scope,
        page=page,
        limit=limit,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await services.get_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
async def get_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await services.get_messages(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )


@router.post("/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: str,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    async def event_stream():
        async for item in services.stream_conversation_response(
            db=db,
            conversation_id=conversation_id,
            user_id=current_user.id,
            content=data.content,
        ):
            event = item["event"]
            payload = json.dumps(item["data"])

            yield f"event: {event}\ndata: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/{conversation_id}/messages/{message_id}/feedback",
    response_model=MessageFeedbackResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_message_feedback(
    conversation_id: str,
    message_id: str,
    data: MessageFeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    message = await services.update_message_feedback(
        db=db,
        user_id=current_user.id,
        conversation_id=conversation_id,
        message_id=message_id,
        rating=data.rating,
    )

    feedback = message.message_metadata["feedback"]

    return MessageFeedbackResponse(
        message_id=message.id,
        rating=feedback["rating"],
    )


@router.post("/{conversation_id}/messages/{message_id}/regenerate")
async def regenerate_message(
    conversation_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    async def event_generator():
        async for event in services.regenerate_conversation_response(
            db=db,
            conversation_id=conversation_id,
            user_id=current_user.id,
            message_id=message_id,
        ):
            yield format_sse(
                event=event["event"],
                data=event["data"],
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
