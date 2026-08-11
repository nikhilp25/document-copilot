"""`source_documents` — one SEC filing per row."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column, updated_at_column


class SourceDocument(Base):
    """One SEC filing, with its normalized Markdown extraction.

    Keeping the Markdown here means re-chunking never has to reach back into
    the gitignored downloaded HTML, which only exists on the ingesting machine.
    """

    __tablename__ = "source_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )

    # Natural key from EDGAR. Unique, so re-running ingestion is idempotent.
    accession_number: Mapped[str] = mapped_column(Text, unique=True)

    ticker: Mapped[str] = mapped_column(Text, index=True)
    company_name: Mapped[str | None] = mapped_column(Text)
    cik: Mapped[str] = mapped_column(Text)
    form_type: Mapped[str] = mapped_column(Text)

    filing_date: Mapped[date] = mapped_column(Date)
    report_date: Mapped[date | None] = mapped_column(Date)
    # Denormalized from `report_date` so citations and filters can say
    # "FY2024" without every caller re-deriving it.
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)

    source_url: Mapped[str] = mapped_column(Text)
    markdown: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
