"""The four reads hybrid retrieval needs from `document_chunks`.

The two ranked searches go through Postgres functions (see the
`eb1fd84894ef` migration) because PostgREST can neither order by vector
distance nor rank a full-text match. The two lookups behind `read_chunk` and
`read_surrounding_chunks` are ordinary table reads and stay on PostgREST.

Service-role throughout, matching `database/chunks.py` and `documents.py`: the
corpus is shared reference data with no analyst behind it.

Nothing here shapes rows. Every function returns what Postgres returned, and
`retriever.py` owns the mapping into `SourcePassage`.
"""

import uuid
from typing import Any

from app.database.chunks import to_vector_literal
from app.database.supabase import service_client

SEMANTIC_FUNCTION = "match_chunks_semantic"
LEXICAL_FUNCTION = "match_chunks_lexical"

# The same columns the search functions return, so a chunk read back by id is
# indistinguishable from one that arrived through a ranked search.
_CHUNK_COLUMNS = "id, document_id, chunk_index, content, section, page, metadata"


async def semantic_search(
    embedding: list[float], *, limit: int, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Nearest chunks by cosine similarity to `embedding`.

    The vector is sent as pgvector's text form, not a JSON array — see
    `to_vector_literal`, which documents why the array form fails to cast.

    Deliberately a POST (the client's default) rather than `rpc(..., get=True)`:
    a 1536-dimension literal is ~20 KB and would not survive a query string.
    """
    client = await service_client()
    response = await client.rpc(
        SEMANTIC_FUNCTION,
        {
            "query_embedding": to_vector_literal(embedding),
            "match_count": limit,
            "filter": filters,
        },
    ).execute()
    return response.data


async def lexical_search(
    query: str, *, limit: int, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Best-ranked chunks whose full-text vector matches `query`.

    `query` goes in as the analyst's own words. `analyst_tsquery` inside the
    database turns it into an OR of its lexemes and `ts_rank_cd` ranks by how
    well a chunk covers them — a whole question ANDed together would match
    nothing. A query with no indexable terms returns no rows rather than
    raising.
    """
    client = await service_client()
    response = await client.rpc(
        LEXICAL_FUNCTION,
        {"query_text": query, "match_count": limit, "filter": filters},
    ).execute()
    return response.data


async def chunk_by_id(chunk_id: uuid.UUID) -> dict[str, Any] | None:
    """One chunk, or None if it is no longer in the corpus.

    Nullable because a re-ingest replaces chunk rows: an id the agent saw
    earlier in the same conversation can legitimately be gone.
    """
    client = await service_client()
    response = (
        await client.table("document_chunks")
        .select(_CHUNK_COLUMNS)
        .eq("id", str(chunk_id))
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


async def neighbor_chunks(
    document_id: uuid.UUID, chunk_index: int, *, radius: int
) -> list[dict[str, Any]]:
    """The chunks within `radius` positions of `chunk_index`, in reading order.

    Served by the `(document_id, chunk_index)` unique constraint. The window is
    clamped at zero only to keep the filter honest; a negative bound would
    match nothing anyway.
    """
    client = await service_client()
    response = (
        await client.table("document_chunks")
        .select(_CHUNK_COLUMNS)
        .eq("document_id", str(document_id))
        .gte("chunk_index", max(chunk_index - radius, 0))
        .lte("chunk_index", chunk_index + radius)
        .order("chunk_index")
        .execute()
    )
    return response.data
