"""OpenAI embedding generation.

Shared deliberately between corpus ingestion and query-time retrieval. Both
sides must embed with the same model and width, or the query vector lands in a
different space than the corpus and every similarity score is meaningless.
"""

from openai import AsyncOpenAI

from app.config import settings
from app.database.models.document_chunks import EMBEDDING_DIMENSIONS

# The API caps a single request well above this, but requests carrying a few
# hundred chunk-sized inputs are already large enough to risk a timeout, and a
# failed batch costs the tokens it already spent.
BATCH_SIZE = 128

_client: AsyncOpenAI | None = None


def _openai_client() -> AsyncOpenAI:
    """Built on first use so importing this module opens no sockets."""
    global _client

    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed `texts`, returning one vector per input in the same order.

    Order matters more than it looks: callers zip the result back onto chunk
    ids, so a reordered response would silently attach every embedding to the
    wrong passage. The API returns an explicit index per item, and this sorts
    on it rather than trusting position.
    """
    if settings.openai_embedding_dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"OPENAI_EMBEDDING_DIMENSIONS is {settings.openai_embedding_dimensions}, "
            f"but document_chunks.embedding is vector({EMBEDDING_DIMENSIONS}). "
            "Changing the width needs a migration that rebuilds the HNSW index."
        )

    vectors: list[list[float]] = []

    for start in range(0, len(texts), BATCH_SIZE):
        response = await _openai_client().embeddings.create(
            model=settings.openai_embedding_model,
            input=texts[start : start + BATCH_SIZE],
            dimensions=settings.openai_embedding_dimensions,
        )
        vectors.extend(
            item.embedding for item in sorted(response.data, key=lambda i: i.index)
        )

    return vectors


async def embed_text(text: str) -> list[float]:
    """Embed a single string — the query side of retrieval."""
    return (await embed_texts([text]))[0]


async def close_client() -> None:
    """Release the OpenAI client's connections.

    The client caches sockets bound to the event loop that created it, so a
    long-lived process that keeps it past that loop's life gets a dead
    transport rather than a reconnect. Call once when the loop is done with it.
    """
    global _client

    if _client is not None:
        await _client.close()
        _client = None
