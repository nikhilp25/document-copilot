"""How retrieval assembles its four reads.

Supabase is replaced with a recorder, so these assert the request that would
have gone out rather than any result. Two of the four go through Postgres
functions, where a wrongly shaped parameter fails at the database with a cast
error rather than anywhere useful.
"""

from typing import Any

import pytest

from app.retrieval import queries

CHUNK_ID = "33333333-3333-4333-8333-333333333333"
DOCUMENT_ID = "44444444-4444-4444-8444-444444444444"

ROW: dict[str, Any] = {
    "id": CHUNK_ID,
    "document_id": DOCUMENT_ID,
    "chunk_index": 7,
    "content": "Item 1A. Risk Factors — export controls.",
    "section": "Item 1A. Risk Factors",
    "page": None,
    "metadata": {"ticker": "NVDA"},
}


class FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class FakeBuilder:
    """Records the PostgREST call it was asked to build."""

    def __init__(self, call: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        self.call = call
        self.rows = rows

    def select(self, columns: str) -> "FakeBuilder":
        self.call["columns"] = columns
        return self

    def eq(self, column: str, value: Any) -> "FakeBuilder":
        self.call.setdefault("filters", {})[f"{column}.eq"] = value
        return self

    def gte(self, column: str, value: Any) -> "FakeBuilder":
        self.call.setdefault("filters", {})[f"{column}.gte"] = value
        return self

    def lte(self, column: str, value: Any) -> "FakeBuilder":
        self.call.setdefault("filters", {})[f"{column}.lte"] = value
        return self

    def order(self, column: str) -> "FakeBuilder":
        self.call["order"] = column
        return self

    def limit(self, count: int) -> "FakeBuilder":
        self.call["limit"] = count
        return self

    async def execute(self) -> FakeResponse:
        return FakeResponse(self.rows)


class FakeClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.call: dict[str, Any] = {}

    def rpc(self, function: str, params: dict[str, Any]) -> FakeBuilder:
        self.call = {"function": function, "params": params}
        return FakeBuilder(self.call, self.rows)

    def table(self, name: str) -> FakeBuilder:
        self.call = {"table": name}
        return FakeBuilder(self.call, self.rows)


@pytest.fixture
def supabase(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient([ROW])

    async def service_client() -> FakeClient:
        return client

    monkeypatch.setattr(queries, "service_client", service_client)
    return client


@pytest.mark.anyio
async def test_semantic_search_sends_a_pgvector_literal(supabase: FakeClient) -> None:
    """A JSON array reaches Postgres as an array and fails to cast to vector."""
    await queries.semantic_search([0.5, -0.25], limit=50, filters={})

    embedding = supabase.call["params"]["query_embedding"]
    assert isinstance(embedding, str)
    assert embedding == "[0.5,-0.25]"


@pytest.mark.anyio
async def test_semantic_search_passes_the_limit_and_filter(
    supabase: FakeClient,
) -> None:
    await queries.semantic_search(
        [0.1], limit=50, filters={"ticker": "NVDA", "fiscal_year": 2025}
    )

    assert supabase.call["function"] == queries.SEMANTIC_FUNCTION
    assert supabase.call["params"]["match_count"] == 50
    assert supabase.call["params"]["filter"] == {"ticker": "NVDA", "fiscal_year": 2025}


@pytest.mark.anyio
async def test_an_unfiltered_search_sends_an_empty_containment_object(
    supabase: FakeClient,
) -> None:
    """`metadata @> '{}'` matches every row, so "no filter" needs no branch."""
    await queries.semantic_search([0.1], limit=10, filters={})

    assert supabase.call["params"]["filter"] == {}


@pytest.mark.anyio
async def test_lexical_search_sends_the_question_unparsed(
    supabase: FakeClient,
) -> None:
    """`websearch_to_tsquery` does the parsing, inside Postgres."""
    await queries.lexical_search(
        "export controls to China?", limit=50, filters={"ticker": "NVDA"}
    )

    assert supabase.call["function"] == queries.LEXICAL_FUNCTION
    assert supabase.call["params"]["query_text"] == "export controls to China?"
    assert supabase.call["params"]["match_count"] == 50
    assert supabase.call["params"]["filter"] == {"ticker": "NVDA"}


@pytest.mark.anyio
async def test_chunk_by_id_reads_one_row(supabase: FakeClient) -> None:
    row = await queries.chunk_by_id(CHUNK_ID)

    assert supabase.call["table"] == "document_chunks"
    assert supabase.call["filters"]["id.eq"] == CHUNK_ID
    assert supabase.call["limit"] == 1
    assert row == ROW


@pytest.mark.anyio
async def test_chunk_by_id_is_none_when_re_ingest_replaced_the_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def service_client() -> FakeClient:
        return FakeClient([])

    monkeypatch.setattr(queries, "service_client", service_client)

    assert await queries.chunk_by_id(CHUNK_ID) is None


@pytest.mark.anyio
async def test_neighbor_chunks_windows_around_the_anchor(
    supabase: FakeClient,
) -> None:
    await queries.neighbor_chunks(DOCUMENT_ID, 7, radius=2)

    filters = supabase.call["filters"]
    assert filters["document_id.eq"] == DOCUMENT_ID
    assert filters["chunk_index.gte"] == 5
    assert filters["chunk_index.lte"] == 9
    # Reading order, not relevance order — the point is contiguous prose.
    assert supabase.call["order"] == "chunk_index"


@pytest.mark.anyio
async def test_neighbor_window_clamps_at_the_start_of_a_filing(
    supabase: FakeClient,
) -> None:
    await queries.neighbor_chunks(DOCUMENT_ID, 0, radius=3)

    assert supabase.call["filters"]["chunk_index.gte"] == 0
