"""The passage route against the real ingested corpus.

Excluded from the fast suite: this needs live Supabase and OpenAI credentials.
It is the only check that a chunk id taken off a citation actually resolves —
that the neighbour query runs against real rows, and that a real chunk's
metadata satisfies the response model rather than only the fixture's.

Run with `uv run pytest -m integration`.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app import embeddings
from app.auth.dependencies import CurrentUser, get_current_user
from app.database.supabase import close_http_client
from app.main import app
from app.retrieval.retriever import DocumentRetriever

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _clients_per_event_loop() -> AsyncIterator[None]:
    """See `tests/retrieval/test_retrieval_integration.py` — same reason."""
    yield
    await close_http_client()
    await embeddings.close_client()


@pytest.mark.anyio
async def test_a_real_citation_resolves_to_its_passage(user: CurrentUser) -> None:
    hits = await DocumentRetriever().search(
        "export controls on data center compute", ticker="NVDA"
    )
    assert hits, "no search results — is the corpus ingested?"
    cited = hits[0]

    # The shared HTTP pool is bound to whichever event loop first used it, and
    # `TestClient` runs the app on a loop of its own. Hand back the sockets this
    # search opened so the app builds its pool on the loop it will run on.
    await close_http_client()
    await embeddings.close_client()

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            body = client.get(f"/passages/{cited.chunk_id}").json()
    finally:
        app.dependency_overrides.clear()

    assert body["content"] == cited.content
    assert body["ticker"] == "NVDA"
    # Chunk 0 of a filing has nothing before it; anything else has both sides.
    assert body["contextBefore"] is not None or body["contextAfter"] is not None
