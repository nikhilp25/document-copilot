"""Hybrid retrieval against the real ingested corpus.

Excluded from the fast suite: these need live Supabase and OpenAI credentials
and cost a few embedding tokens per run. They are the only check that the two
Postgres functions exist, that PostgREST can see them, and that the `english`
regconfig on the query side matches the one baked into `search_vector` — none
of which a mocked test can tell you.

Run with `uv run pytest -m integration`.
"""

import uuid
from collections.abc import AsyncIterator

import pytest

from app import embeddings
from app.database.supabase import close_http_client
from app.retrieval import queries
from app.retrieval.fusion import RRF_K
from app.retrieval.retriever import CANDIDATE_LIMIT, DocumentRetriever

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture(autouse=True)
async def _clients_per_event_loop() -> AsyncIterator[None]:
    """Drop the cached HTTP clients between tests.

    Both the Supabase pool and the OpenAI client are module globals built on
    first use, and anyio runs each test on a fresh event loop. Without this the
    second test reaches for sockets belonging to the first test's dead loop.
    The app itself has one loop for its lifetime, so this is a test concern.
    """
    yield
    await close_http_client()
    await embeddings.close_client()


@pytest.fixture
def retriever() -> DocumentRetriever:
    return DocumentRetriever()


async def test_the_full_text_function_matches_the_generated_regconfig() -> None:
    """A mismatched `to_tsquery` config returns zero rows instead of an error."""
    rows = await queries.lexical_search(
        "export controls", limit=CANDIDATE_LIMIT, filters={}
    )

    assert rows, "no lexical matches — check the 'english' regconfig and the GIN index"
    assert all(row["score"] > 0 for row in rows)


async def test_a_whole_question_still_reaches_the_lexical_arm() -> None:
    """The failure this arm shipped with: ANDed lexemes match no single chunk.

    Every tsquery builder Postgres ships ANDs its terms, so a real analyst
    question returned nothing and hybrid search quietly ran on one leg.
    `analyst_tsquery` ORs them instead.
    """
    rows = await queries.lexical_search(
        "How did NVIDIA describe demand drivers, customer concentration, and "
        "supply constraints for its Data Center business?",
        limit=CANDIDATE_LIMIT,
        filters={},
    )

    assert len(rows) == CANDIDATE_LIMIT


async def test_both_arms_contribute_to_a_fused_result(
    retriever: DocumentRetriever,
) -> None:
    """A top passage scoring above one arm's best possible means both voted."""
    question = "What does NVIDIA say about data center demand and supply?"

    passages = await retriever.search(question, top_k=5)
    single_arm_best = 1.0 / (RRF_K + 1)

    assert passages[0].score is not None
    assert passages[0].score > single_arm_best


async def test_a_paraphrased_question_finds_the_right_filer_and_item(
    retriever: DocumentRetriever,
) -> None:
    """The Phase 4 spot check, now through the whole hybrid path."""
    passages = await retriever.search(
        "How do US export restrictions on chips to China affect NVIDIA?"
    )

    top = passages[:5]
    assert any(passage.ticker == "NVDA" for passage in top)
    assert any(
        passage.section is not None and passage.section.startswith("Item 1A")
        for passage in top
    )


async def test_a_rare_exact_phrase_is_found_by_the_lexical_arm(
    retriever: DocumentRetriever,
) -> None:
    """The case dense retrieval smooths over: a named segment, spelled exactly."""
    passages = await retriever.search("Wearables, Home and Accessories")

    assert any(passage.ticker == "AAPL" for passage in passages)


async def test_a_ticker_filter_excludes_every_other_filer(
    retriever: DocumentRetriever,
) -> None:
    passages = await retriever.search("cloud infrastructure capacity", ticker="MSFT")

    assert passages
    assert {passage.ticker for passage in passages} == {"MSFT"}


async def test_a_fiscal_year_filter_narrows_to_one_filing_year(
    retriever: DocumentRetriever,
) -> None:
    passages = await retriever.search(
        "data center revenue growth", ticker="NVDA", fiscal_year=2025
    )

    assert passages
    assert {passage.fiscal_year for passage in passages} == {2025}


async def test_top_k_is_respected_against_a_real_corpus(
    retriever: DocumentRetriever,
) -> None:
    passages = await retriever.search("supplier concentration", top_k=3)

    assert len(passages) == 3
    # Fusion dedupes across arms; duplicates here would mean it did not.
    assert len({passage.chunk_id for passage in passages}) == 3


async def test_neighbours_are_contiguous_and_include_the_anchor(
    retriever: DocumentRetriever,
) -> None:
    hit = (await retriever.search("supplier concentration", top_k=1))[0]

    window = await retriever.read_surrounding_chunks(hit.chunk_id, radius=1)
    indexes = [passage.chunk_index for passage in window]

    assert hit.chunk_index in indexes
    assert indexes == list(range(indexes[0], indexes[0] + len(indexes)))
    assert {passage.document_id for passage in window} == {hit.document_id}


async def test_reading_a_retired_chunk_id_is_not_an_error(
    retriever: DocumentRetriever,
) -> None:
    """Re-ingesting the corpus replaces chunk rows; the agent must survive it."""
    assert await retriever.read_chunk(uuid.uuid4()) is None
    assert await retriever.read_surrounding_chunks(uuid.uuid4()) == []
