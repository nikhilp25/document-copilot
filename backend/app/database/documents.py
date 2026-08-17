"""`source_documents` persistence.

Corpus ingestion has no analyst behind it, so everything here runs through the
service-role client and bypasses RLS. Nothing in this module is user-scoped —
one corpus is shared by every analyst, unlike the chat tables next door.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.database.supabase import service_client

_DOCUMENT_COLUMNS = "id, accession_number, ticker, form_type, fiscal_year, filing_date"


async def upsert_source_document(document: dict[str, Any]) -> uuid.UUID:
    """Write one filing, replacing any earlier ingest of the same accession.

    `accession_number` is EDGAR's natural key and unique in the table, so a
    re-run updates in place rather than duplicating the corpus.
    """
    # `updated_at` has an `onupdate` in the model, but that only fires on
    # SQLAlchemy writes and this one goes through PostgREST.
    row = document | {"updated_at": datetime.now(UTC).isoformat()}

    client = await service_client()
    response = (
        await client.table("source_documents")
        .upsert(row, on_conflict="accession_number")
        .execute()
    )
    return uuid.UUID(response.data[0]["id"])


async def list_source_documents() -> list[dict[str, Any]]:
    """Every filing in the corpus, most recently filed first.

    Metadata only — `markdown` is megabytes per row and no caller wants the
    whole corpus in memory.
    """
    client = await service_client()
    response = (
        await client.table("source_documents")
        .select(_DOCUMENT_COLUMNS)
        .order("filing_date", desc=True)
        .execute()
    )
    return response.data
