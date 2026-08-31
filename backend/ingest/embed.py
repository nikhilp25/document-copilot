"""Embed the chunks that don't have vectors yet.

Run from `backend/`, after `ingest.chunks`:

    uv run python -m ingest.embed

This is the only step that spends money, so it is built to never spend it
twice. It selects on `embedding IS NULL`, writes each vector as it arrives, and
picks up exactly where it left off — interrupt it freely.

Set `CHUNK_LIMIT = 1` to embed a single chunk end to end before committing to
the corpus.
"""

from __future__ import annotations

import asyncio
import uuid

from app.database.chunks import (
    chunks_missing_embeddings,
    count_missing_embeddings,
    set_chunk_embedding,
)
from app.database.supabase import close_http_client
from app.embeddings import BATCH_SIZE, embed_texts

# None embeds the whole backlog. A small number is the smoke test.
CHUNK_LIMIT: int | None = None

# Vectors are written one row at a time (PostgREST has no bulk update), so the
# writes are overlapped. Kept modest: this shares a connection pool.
WRITE_CONCURRENCY = 12


async def embed_pending(chunk_limit: int | None = None) -> int:
    """Embed and store pending chunks. Returns how many were embedded."""
    embedded = 0

    while chunk_limit is None or embedded < chunk_limit:
        remaining = BATCH_SIZE if chunk_limit is None else chunk_limit - embedded
        pending = await chunks_missing_embeddings(min(BATCH_SIZE, remaining))

        if not pending:
            break

        vectors = await embed_texts([chunk["content"] for chunk in pending])
        await _write_vectors(pending, vectors)

        embedded += len(pending)
        print(f"  embedded {embedded:,} chunk(s)")

    return embedded


async def _write_vectors(
    pending: list[dict[str, str]], vectors: list[list[float]]
) -> None:
    semaphore = asyncio.Semaphore(WRITE_CONCURRENCY)

    async def write(chunk_id: str, embedding: list[float]) -> None:
        async with semaphore:
            await set_chunk_embedding(uuid.UUID(chunk_id), embedding)

    await asyncio.gather(
        *(
            write(chunk["id"], vector)
            for chunk, vector in zip(pending, vectors, strict=True)
        )
    )


async def main() -> int:
    before = await count_missing_embeddings()
    print(f"{before:,} chunk(s) awaiting embeddings.")

    embedded = await embed_pending(CHUNK_LIMIT)
    after = await count_missing_embeddings()
    await close_http_client()

    print(f"\nEmbedded {embedded:,} chunk(s). {after:,} still pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
