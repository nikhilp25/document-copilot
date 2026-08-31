"""`document_chunks` persistence.

Service-role throughout, for the same reason as `documents.py`: the corpus
belongs to no analyst.

Chunks are written in two passes — rows first with a NULL embedding, vectors
afterwards. That split is what makes embedding restartable: the work already
paid for is on disk, and a re-run only asks for what is still NULL.
"""

import uuid
from typing import Any

from app.database.supabase import service_client

_PENDING_COLUMNS = "id, content"

# One statement per row would be thousands of round trips; one statement for
# every row would be a multi-megabyte body. Both writes chunk their work.
#
# Kept small on purpose: the client serializes the whole batch to JSON in
# memory, on top of whatever the caller is already holding. At 200 rows that
# encode step was enough to exhaust memory mid-ingest.
INSERT_BATCH_SIZE = 50


def to_vector_literal(embedding: list[float]) -> str:
    """Render an embedding the way pgvector parses it.

    PostgREST hands JSON to Postgres, where a JSON array of numbers reaches a
    `vector` column as a Postgres array and fails to cast. The text form is
    what `vector_in` actually accepts.
    """
    return f"[{','.join(repr(value) for value in embedding)}]"


async def insert_chunks(rows: list[dict[str, Any]]) -> int:
    """Insert chunk rows, embeddings still NULL. Returns the number written."""
    client = await service_client()
    written = 0

    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[start : start + INSERT_BATCH_SIZE]
        response = await client.table("document_chunks").insert(batch).execute()
        written += len(response.data)

    return written


async def count_chunks(document_id: uuid.UUID) -> int:
    """How many chunks a filing already has — the re-run guard."""
    client = await service_client()
    response = (
        await client.table("document_chunks")
        .select("id", count="exact")
        .eq("document_id", str(document_id))
        .limit(1)
        .execute()
    )
    return response.count or 0


async def delete_chunks_for_document(document_id: uuid.UUID) -> None:
    """Drop a filing's chunks so it can be re-chunked from scratch."""
    client = await service_client()
    await (
        client.table("document_chunks")
        .delete()
        .eq("document_id", str(document_id))
        .execute()
    )


async def chunks_missing_embeddings(limit: int) -> list[dict[str, Any]]:
    """The next chunks still awaiting a vector, oldest first.

    Ordered by `created_at` so repeated calls walk the backlog in a stable
    order instead of re-reading the same page.
    """
    client = await service_client()
    response = (
        await client.table("document_chunks")
        .select(_PENDING_COLUMNS)
        .is_("embedding", "null")
        .order("created_at")
        .limit(limit)
        .execute()
    )
    return response.data


async def count_missing_embeddings() -> int:
    """How much of the corpus is still unembedded."""
    client = await service_client()
    response = (
        await client.table("document_chunks")
        .select("id", count="exact")
        .is_("embedding", "null")
        .limit(1)
        .execute()
    )
    return response.count or 0


async def set_chunk_embedding(chunk_id: uuid.UUID, embedding: list[float]) -> None:
    """Attach one vector to one chunk."""
    client = await service_client()
    await (
        client.table("document_chunks")
        .update({"embedding": to_vector_literal(embedding)})
        .eq("id", str(chunk_id))
        .execute()
    )
