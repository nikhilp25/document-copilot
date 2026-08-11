"""`chat_messages` — user and assistant turns within a thread."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(Base):
    """One user or assistant message, persisted after a turn completes."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_thread_id_created_at", "thread_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_threads.id", ondelete="CASCADE")
    )

    role: Mapped[MessageRole] = mapped_column(
        Enum(
            MessageRole,
            name="chat_message_role",
            values_callable=lambda enum: [member.value for member in enum],
        )
    )

    # Plain text of the message — what retrieval, evaluation, and logs read.
    content: Mapped[str] = mapped_column(Text)

    # The AI SDK UI message parts, stored verbatim so a reloaded thread renders
    # identically to the live stream. NULL for messages built server-side.
    parts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = created_at_column()
