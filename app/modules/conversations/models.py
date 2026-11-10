import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    CheckConstraint,
    JSON,
    Index,
)

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchConversation(Base):
    __tablename__ = "research_conversations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    research_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("research_jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scope: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    research: Mapped["ResearchJob | None"] = relationship(
        "ResearchJob",
        back_populates="conversations",
        passive_deletes=True,
    )

    messages: Mapped[list["ResearchMessage"]] = relationship(
        "ResearchMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "scope IN ('research', 'workspace')",
            name="ck_research_conversations_scope",
        ),
        CheckConstraint(
            """
            (scope = 'research' AND research_id IS NOT NULL)
            OR
            (scope = 'workspace' AND research_id IS NULL)
            """,
            name="ck_research_conversations_scope_research_id",
        ),
        Index(
            "ix_research_conversations_user_updated",
            "user_id",
            "updated_at",
        ),
    )


class ResearchMessage(Base):
    __tablename__ = "research_messages"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("research_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    citations: Mapped[list[dict] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    message_metadata: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    conversation: Mapped["ResearchConversation"] = relationship(
        back_populates="messages",
    )
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_research_messages_role",
        ),
        Index(
            "ix_research_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )
