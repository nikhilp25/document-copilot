"""The retrieval contract the Phase 6 agent will be handed.

Both database arms and the embedding call are replaced with fakes, so these
tests are about ranking policy and passage shaping — the parts that decide
whether an analyst sees the right filing.
"""

import uuid
from typing import Any

import pytest

from app import embeddings
from app.retrieval import queries
from app.retrieval.retriever import (
    CANDIDATE_LIMIT,
    DocumentRetriever,
    SourcePassage,
)

DOCUMENT_ID = "44444444-4444-4444-8444-444444444444"

FILING_METADATA: dict[str, Any] = {
    "ticker": "NVDA",
    "company_name": "NVIDIA Corporation",
    "cik": "0001045810",
    "form_type": "10-K",
    "fiscal_year": 2025,
    "filing_date": "2025-02-26",
    "accession_number": "0001045810-25-000023",
    "source_url": "https://www.sec.gov/Archives/edgar/data/1045810/nvda.htm",
    "section": "Item 1A. Risk Factors",
}


def row(
    chunk_id: str,
    *,
    chunk_index: int = 0,
    section: str | None = "Item 1A. Risk Factors",
    page: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        # Stable per label, so the same name always means the same chunk.
        "id": str(uuid.uuid5(uuid.NAMESPACE_OID, chunk_id)),
        "document_id": DOCUMENT_ID,
        "chunk_index": chunk_index,
        "content": f"passage {chunk_id}",
        "section": section,
        "page": page,
        "metadata": metadata or FILING_METADATA,
    }


class FakeSearch:
    """Stands in for both ranked arms, recording how it was called."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    async def semantic(
        self, embedding: list[float], *, limit: int, filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {"arm": "semantic", "embedding": embedding, "limit": limit, **filters}
        )
        return self.rows

    async def lexical(
        self, query: str, *, limit: int, filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        self.calls.append({"arm": "lexical", "query": query, "limit": limit, **filters})
        return self.rows


@pytest.fixture
def arms(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeSearch]:
    """Independently controllable semantic and lexical arms."""
    semantic = FakeSearch([])
    lexical = FakeSearch([])

    async def embed_text(text: str) -> list[float]:
        return [0.1, 0.2]

    monkeypatch.setattr(embeddings, "embed_text", embed_text)
    monkeypatch.setattr(queries, "semantic_search", semantic.semantic)
    monkeypatch.setattr(queries, "lexical_search", lexical.lexical)

    return {"semantic": semantic, "lexical": lexical}


@pytest.mark.anyio
async def test_search_fuses_the_arms_rather_than_concatenating_them(
    arms: dict[str, FakeSearch],
) -> None:
    """A chunk both arms found outranks either arm's own favourite."""
    both, semantic_only, lexical_only = row("both"), row("sem"), row("lex")
    arms["semantic"].rows = [semantic_only, both]
    arms["lexical"].rows = [lexical_only, both]

    passages = await DocumentRetriever().search("export controls")

    assert [passage.content for passage in passages] == [
        "passage both",
        "passage sem",
        "passage lex",
    ]


@pytest.mark.anyio
async def test_a_chunk_both_arms_returned_appears_once(
    arms: dict[str, FakeSearch],
) -> None:
    shared = row("shared")
    arms["semantic"].rows = [shared]
    arms["lexical"].rows = [shared]

    passages = await DocumentRetriever().search("export controls")

    assert len(passages) == 1


@pytest.mark.anyio
async def test_both_arms_are_asked_for_the_full_candidate_pool(
    arms: dict[str, FakeSearch],
) -> None:
    """Fusion can only rescue a buried chunk if it was fetched in the first place."""
    await DocumentRetriever().search("export controls", top_k=3)

    assert arms["semantic"].calls[0]["limit"] == CANDIDATE_LIMIT
    assert arms["lexical"].calls[0]["limit"] == CANDIDATE_LIMIT


@pytest.mark.anyio
async def test_the_lexical_arm_gets_the_question_and_the_semantic_arm_a_vector(
    arms: dict[str, FakeSearch],
) -> None:
    await DocumentRetriever().search("export controls to China")

    assert arms["semantic"].calls[0]["embedding"] == [0.1, 0.2]
    assert arms["lexical"].calls[0]["query"] == "export controls to China"


@pytest.mark.anyio
async def test_top_k_truncates_after_fusion(arms: dict[str, FakeSearch]) -> None:
    arms["semantic"].rows = [row("a"), row("b"), row("c")]

    passages = await DocumentRetriever().search("export controls", top_k=2)

    assert len(passages) == 2


@pytest.mark.anyio
async def test_filters_reach_both_arms(arms: dict[str, FakeSearch]) -> None:
    await DocumentRetriever().search(
        "export controls", ticker="NVDA", fiscal_year=2025, form_type="10-K"
    )

    for arm in ("semantic", "lexical"):
        call = arms[arm].calls[0]
        assert call["ticker"] == "NVDA"
        assert call["fiscal_year"] == 2025
        assert call["form_type"] == "10-K"


@pytest.mark.anyio
async def test_unset_filters_are_omitted_entirely(
    arms: dict[str, FakeSearch],
) -> None:
    """An absent key is what makes JSONB containment match everything."""
    await DocumentRetriever().search("export controls", ticker="NVDA")

    call = arms["semantic"].calls[0]
    assert call["ticker"] == "NVDA"
    assert "fiscal_year" not in call
    assert "form_type" not in call


@pytest.mark.anyio
async def test_passages_carry_the_metadata_a_citation_needs(
    arms: dict[str, FakeSearch],
) -> None:
    arms["semantic"].rows = [row("a", chunk_index=12)]

    passage = (await DocumentRetriever().search("export controls"))[0]

    assert isinstance(passage, SourcePassage)
    assert passage.ticker == "NVDA"
    assert passage.company_name == "NVIDIA Corporation"
    assert passage.form_type == "10-K"
    assert passage.fiscal_year == 2025
    assert passage.filing_date.isoformat() == "2025-02-26"
    assert passage.accession_number == "0001045810-25-000023"
    assert passage.section == "Item 1A. Risk Factors"
    assert passage.chunk_index == 12
    assert passage.score is not None


@pytest.mark.anyio
async def test_a_chunk_with_no_section_still_maps(
    arms: dict[str, FakeSearch],
) -> None:
    """2.7% of the corpus has no reconstructed heading; page is NULL for all of it."""
    arms["semantic"].rows = [row("a", section=None)]

    passage = (await DocumentRetriever().search("export controls"))[0]

    assert passage.section is None
    assert passage.page is None


@pytest.mark.anyio
async def test_read_chunk_reports_no_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing ranked it, so there is no ranking to report."""

    async def chunk_by_id(chunk_id: Any) -> dict[str, Any]:
        return row("a")

    monkeypatch.setattr(queries, "chunk_by_id", chunk_by_id)

    passage = await DocumentRetriever().read_chunk(row("a")["id"])

    assert passage is not None
    assert passage.score is None


@pytest.mark.anyio
async def test_read_chunk_is_none_when_the_chunk_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def chunk_by_id(chunk_id: Any) -> None:
        return None

    monkeypatch.setattr(queries, "chunk_by_id", chunk_by_id)

    assert await DocumentRetriever().read_chunk(row("a")["id"]) is None


@pytest.mark.anyio
async def test_surrounding_chunks_come_back_in_reading_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = row("b", chunk_index=5)
    window = [row("a", chunk_index=4), anchor, row("c", chunk_index=6)]

    async def chunk_by_id(chunk_id: Any) -> dict[str, Any]:
        return anchor

    async def neighbor_chunks(
        document_id: Any, chunk_index: int, *, radius: int
    ) -> list[dict[str, Any]]:
        assert chunk_index == 5
        return window

    monkeypatch.setattr(queries, "chunk_by_id", chunk_by_id)
    monkeypatch.setattr(queries, "neighbor_chunks", neighbor_chunks)

    passages = await DocumentRetriever().read_surrounding_chunks(anchor["id"])

    assert [passage.chunk_index for passage in passages] == [4, 5, 6]


@pytest.mark.anyio
async def test_surrounding_chunks_is_empty_when_the_anchor_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-ingest can retire an id the agent saw earlier in the same turn."""

    async def chunk_by_id(chunk_id: Any) -> None:
        return None

    monkeypatch.setattr(queries, "chunk_by_id", chunk_by_id)

    assert await DocumentRetriever().read_surrounding_chunks(row("a")["id"]) == []
