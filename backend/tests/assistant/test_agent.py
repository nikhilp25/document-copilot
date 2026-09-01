"""The agent's wiring, driven by a scripted model instead of OpenAI.

`FunctionModel` runs the real agent — real tools, real output schema, real
output validator — with us deciding what the model "says". That is what makes
it possible to test the thing the product actually promises: that an answer
citing something it never retrieved does not get through.
"""

import json
import uuid

import pytest
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.assistant.agent import agent
from app.assistant.deps import DocumentAgentDeps
from tests.assistant.conftest import (
    QUOTE,
    FakeRetriever,
    final,
    script,
    search_call,
)

pytestmark = pytest.mark.anyio


def deps(retriever: FakeRetriever) -> DocumentAgentDeps:
    return DocumentAgentDeps(
        user_id=uuid.uuid4(), thread_id=uuid.uuid4(), retriever=retriever
    )


async def test_a_search_records_what_the_model_was_shown(
    retriever: FakeRetriever,
) -> None:
    """The ledger is what grounding checks against, so tools must fill it."""
    found = retriever.passages[0]
    run_deps = deps(retriever)

    model = script(
        lambda info: search_call(query="export controls", ticker="NVDA"),
        lambda info: final(
            info,
            answer="Export controls cut China sales [1].",
            has_evidence=True,
            citations=[{"index": 1, "chunk_id": str(found.chunk_id), "quote": QUOTE}],
        ),
    )

    with agent.override(model=model):
        result = await agent.run("Why did NVIDIA's China sales fall?", deps=run_deps)

    assert run_deps.retrieved == {found.chunk_id: found}
    assert result.output.citations[0].chunk_id == found.chunk_id


async def test_the_models_filters_reach_the_retriever(
    retriever: FakeRetriever,
) -> None:
    found = retriever.passages[0]

    model = script(
        lambda info: search_call(
            query="data centre demand", ticker="NVDA", fiscal_year=2025
        ),
        lambda info: final(
            info,
            answer="Demand rose [1].",
            has_evidence=True,
            citations=[{"index": 1, "chunk_id": str(found.chunk_id), "quote": QUOTE}],
        ),
    )

    with agent.override(model=model):
        await agent.run("How was data centre demand?", deps=deps(retriever))

    assert retriever.searches == [
        {"query": "data centre demand", "ticker": "NVDA", "fiscal_year": 2025}
    ]


async def test_an_ungrounded_answer_is_sent_back_for_correction(
    retriever: FakeRetriever,
) -> None:
    """A fixable citation costs one more request, not the whole turn."""
    found = retriever.passages[0]
    attempts: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = sum(1 for message in messages if isinstance(message, ModelResponse))
        if step == 0:
            return search_call(query="export controls")
        if step == 1:
            # Cites a chunk no tool ever returned.
            return final(
                info,
                answer="China sales fell [1].",
                has_evidence=True,
                citations=[{"index": 1, "chunk_id": str(uuid.uuid4()), "quote": QUOTE}],
            )
        attempts.append(_retry_text(messages))
        return final(
            info,
            answer="China sales fell [1].",
            has_evidence=True,
            citations=[{"index": 1, "chunk_id": str(found.chunk_id), "quote": QUOTE}],
        )

    with agent.override(model=FunctionModel(respond)):
        result = await agent.run("Why did China sales fall?", deps=deps(retriever))

    assert result.output.citations[0].chunk_id == found.chunk_id
    # The model was told exactly what was wrong, not just that something was.
    assert "no search or read tool returned this turn" in attempts[0]


async def test_an_answer_that_stays_ungrounded_never_returns(
    retriever: FakeRetriever,
) -> None:
    """Fail closed: the analyst gets an error, never the unsupported answer."""
    model = script(
        lambda info: search_call(query="export controls"),
        lambda info: final(
            info,
            answer="China sales fell [1].",
            has_evidence=True,
            citations=[{"index": 1, "chunk_id": str(uuid.uuid4()), "quote": QUOTE}],
        ),
    )

    with agent.override(model=model), pytest.raises(UnexpectedModelBehavior):
        await agent.run("Why did China sales fall?", deps=deps(retriever))


async def test_a_refusal_needs_no_citations(retriever: FakeRetriever) -> None:
    """ "Not in the corpus" must pass the same gate a real answer does."""
    model = script(
        lambda info: search_call(query="Tesla margins"),
        lambda info: final(
            info,
            answer="These filings do not cover Tesla.",
            has_evidence=False,
            citations=[],
        ),
    )

    with agent.override(model=model):
        result = await agent.run("What are Tesla's margins?", deps=deps(retriever))

    assert result.output.has_evidence is False
    assert result.output.citations == []


def _retry_text(messages: list[ModelMessage]) -> str:
    """The correction PydanticAI sent back after the validator refused."""
    return json.dumps(
        [
            part.model_dump(mode="json") if hasattr(part, "model_dump") else str(part)
            for message in messages
            for part in getattr(message, "parts", [])
            if getattr(part, "part_kind", "") == "retry-prompt"
        ],
        default=str,
    )
