"""The agent against the real model and the real corpus.

Excluded from the fast suite: these spend OpenAI tokens and take tens of
seconds each. They are the only check that the instructions, the tool schemas
and the grounding validator work together on a live model rather than a
scripted one — a `FunctionModel` can prove the gate closes, but only this can
prove a real model gets through it.

Run with `uv run pytest -m integration`.
"""

import uuid
from collections.abc import AsyncIterator

import pytest

from app import embeddings
from app.assistant.agent import USAGE_LIMITS, agent
from app.assistant.deps import DocumentAgentDeps
from app.assistant.outputs import GroundedAnswer
from app.database.supabase import close_http_client
from app.grounding.validator import violations
from app.retrieval.retriever import DocumentRetriever

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture(autouse=True)
async def _clients_per_event_loop() -> AsyncIterator[None]:
    """Drop the cached HTTP clients between tests.

    Both the Supabase pool and the OpenAI client are module globals built on
    first use, and anyio runs each test on a fresh event loop.
    """
    yield
    await close_http_client()
    await embeddings.close_client()


@pytest.fixture
def deps() -> DocumentAgentDeps:
    return DocumentAgentDeps(
        user_id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        retriever=DocumentRetriever(),
    )


async def ask(question: str, deps: DocumentAgentDeps) -> GroundedAnswer:
    result = await agent.run(question, deps=deps, usage_limits=USAGE_LIMITS)
    return result.output


async def test_a_corpus_question_is_answered_with_checkable_citations(
    deps: DocumentAgentDeps,
) -> None:
    """Client brief question 3, end to end."""
    answer = await ask(
        "How did NVIDIA describe demand drivers and supply constraints for its "
        "Data Center business?",
        deps,
    )

    assert answer.has_evidence is True
    assert answer.citations
    # Whatever the model wrote, it has to survive the same gate the turn uses.
    assert violations(answer, deps.retrieved) == []
    assert any(
        deps.retrieved[citation.chunk_id].ticker == "NVDA"
        for citation in answer.citations
    )


async def test_every_quote_is_really_in_the_passage_it_names(
    deps: DocumentAgentDeps,
) -> None:
    """The claim an analyst clicks through to verify."""
    answer = await ask(
        "What does Apple say about depending on third-party manufacturing?", deps
    )

    for citation in answer.citations:
        passage = deps.retrieved[citation.chunk_id]
        assert " ".join(citation.quote.split()) in " ".join(passage.content.split())


async def test_a_company_outside_the_corpus_is_refused(
    deps: DocumentAgentDeps,
) -> None:
    """The corpus holds five filers; Tesla is not one of them."""
    answer = await ask("What are Tesla's gross margins and how have they moved?", deps)

    assert answer.has_evidence is False
    assert answer.citations == []


async def test_question_ten_stays_traceable_to_the_filings(
    deps: DocumentAgentDeps,
) -> None:
    """The brief's trap: the filings do not prove generative AI moved margins.

    There is no keyword that distinguishes asserting the causal claim from
    denying it — a good answer says "do not prove" and a bad one says "prove",
    and both contain the word. What is checkable, and what actually stops the
    inference, is that every sentence carrying a claim is pinned to a verbatim
    quote from a passage retrieved this turn. A model cannot reason its way to
    a margin conclusion the filings never state and still pass this.
    """
    answer = await ask(
        "Do the filings prove that generative AI improved margins for any of "
        "these companies?",
        deps,
    )

    assert violations(answer, deps.retrieved) == []
    # It engaged with the question rather than returning a shrug.
    assert len(answer.answer) > 100
    if answer.has_evidence:
        assert all(
            " ".join(citation.quote.split())
            in " ".join(deps.retrieved[citation.chunk_id].content.split())
            for citation in answer.citations
        )


async def test_a_cross_company_question_searches_each_filer(
    deps: DocumentAgentDeps,
) -> None:
    """Filters take one ticker, so coverage comes from repeated tool calls."""
    answer = await ask(
        "Compare what Microsoft and Amazon say about cloud capacity constraints.",
        deps,
    )

    tickers = {passage.ticker for passage in deps.retrieved.values()}

    assert {"MSFT", "AMZN"} <= tickers
    assert violations(answer, deps.retrieved) == []
