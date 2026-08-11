"""`chat_threads` — one conversation, owned by exactly one user."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column, updated_at_column


class ChatThread(Base):
    """A conversation owned by exactly one user."""

    __tablename__ = "chat_threads"
    __table_args__ = (
        # The sidebar query: this user's threads, most recently active first.
        Index("ix_chat_threads_user_id_updated_at", "user_id", text("updated_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )

    # NULL until the first turn completes and a title is derived from it.
    title: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
