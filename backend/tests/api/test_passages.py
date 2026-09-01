"""The passage route: what a citation click resolves to.

The retriever itself is Phase 5's, tested there against a real corpus. What
these check is the part this route decides — that a caller must be signed in,
that the cited chunk is separated from its neighbours in reading order, and
that a chunk which has left the corpus is a 404 rather than a blank panel.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.passages import get_retriever
from app.main import app
from app.retrieval.retriever import SourcePassage
from tests.assistant.conftest import FakeRetriever, passage


@pytest.fixture
def window() -> list[SourcePassage]:
    """Three consecutive chunks of one filing, in reading order."""
    document_id = uuid.uuid4()
    chunks = [passage(chunk_index=index) for index in (6, 7, 8)]

    for index, chunk in enumerate(chunks):
        chunks[index] = chunk.model_copy(
            update={
                "document_id": document_id,
                "content": f"Chunk {chunk.chunk_index}.",
            }
        )
    return chunks


@pytest.fixture
def corpus(window: list[SourcePassage]) -> Iterator[FakeRetriever]:
    retriever = FakeRetriever(window)
    app.dependency_overrides[get_retriever] = lambda: retriever
    yield retriever
    # `signed_in` clears every override on its own teardown, and which of the
    # two runs first is not worth depending on.
    app.dependency_overrides.pop(get_retriever, None)


def test_rejects_requests_without_a_token(client: TestClient) -> None:
    response = client.get(f"/passages/{uuid.uuid4()}")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_returns_the_cited_chunk_with_its_neighbours(
    signed_in: TestClient, corpus: FakeRetriever
) -> None:
    cited = corpus.passages[1]

    body = signed_in.get(f"/passages/{cited.chunk_id}").json()

    assert body["content"] == "Chunk 7."
    # Split on reading order, so the panel can dim what came before and after
    # without knowing anything about chunk indices.
    assert body["contextBefore"] == "Chunk 6."
    assert body["contextAfter"] == "Chunk 8."


def test_carries_the_metadata_a_citation_panel_labels_with(
    signed_in: TestClient, corpus: FakeRetriever
) -> None:
    cited = corpus.passages[1]

    body = signed_in.get(f"/passages/{cited.chunk_id}").json()

    assert body["ticker"] == "NVDA"
    assert body["formType"] == "10-K"
    assert body["fiscalYear"] == 2025
    assert body["filingDate"] == "2025-02-26"
    assert body["section"] == "Item 1A. Risk Factors"
    assert body["sourceUrl"].startswith("https://www.sec.gov/")
    # Retrieval's own bookkeeping stays on the server side of the wire.
    assert "score" not in body
    assert "chunkIndex" not in body


def test_omits_context_at_the_edges_of_a_filing(
    signed_in: TestClient, window: list[SourcePassage]
) -> None:
    first = window[0]
    app.dependency_overrides[get_retriever] = lambda: FakeRetriever(window[:2])

    body = signed_in.get(f"/passages/{first.chunk_id}").json()

    assert body["contextBefore"] is None
    assert body["contextAfter"] == "Chunk 7."

    app.dependency_overrides.pop(get_retriever, None)


def test_reingested_away_passage_is_a_404(
    signed_in: TestClient, corpus: FakeRetriever
) -> None:
    response = signed_in.get(f"/passages/{uuid.uuid4()}")

    assert response.status_code == 404
    assert "no longer in the corpus" in response.json()["detail"]
