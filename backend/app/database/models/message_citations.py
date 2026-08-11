"""`message_citations` — the evidence backing each assistant answer."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column


class MessageCitation(Base):
    """A single citation on an assistant message.

    `chunk_id` and `document_id` are `ON DELETE SET NULL` rather than CASCADE,
    and the excerpt/page/section are snapshotted at answer time. Re-ingesting
    the corpus replaces chunk rows, and a citation that silently vanished — or
    that started pointing at different text — would break the one guarantee
    this product makes.
    """

    __tablename__ = "message_citations"
    __table_args__ = (UniqueConstraint("message_id", "citation_index"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_messages.id", ondelete="CASCADE")
    )

    # Order the citation appears in the answer; drives the [1], [2] markers.
    citation_index: Mapped[int] = mapped_column(Integer)

    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("source_documents.id", ondelete="SET NULL")
    )

    excerpt: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = created_at_column()
