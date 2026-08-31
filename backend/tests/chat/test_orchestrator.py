"""One turn, from question to persisted answer.

The agent runs for real against a scripted model, so these exercise the thing
the orchestrator exists to guarantee: an answer that fails the citation check
never reaches the stream, and nothing is written when it does not.
"""

import json
import uuid
from typing import Any

import pytest
from pydantic_ai.models.function import FunctionModel

from app.assistant.agent import agent
from app.auth.dependencies import CurrentUser
from app.chat import messages as ui
from app.chat import orchestrator
from app.database import chats
from app.database import citations as citation_rows
from app.database.chats import ThreadRef
from tests.assistant.conftest import (
    QUOTE,
    FakeRetriever,
    final,
    script,
    search_call,
)

pytestmark = pytest.mark.anyio


class Persisted:
    """In-memory stand-ins for the two writes a completed turn makes."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.citations: list[dict[str, Any]] = []

    async def append_message(
        self, user: CurrentUser, thread_id: uuid.UUID, **row: Any
    ) -> dict[str, Any]:
        self.messages.append({"thread_id": thread_id, **row})
        return {"id": str(row.get("message_id"))}

    async def insert_citations(
        self, user: CurrentUser, message_id: uuid.UUID, citations: list[dict[str, Any]]
    ) -> None:
        self.citations.extend(
            {"message_id": message_id, **citation} for citation in citations
        )


@pytest.fixture(autouse=True)
def _instant_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.chat.streaming._DELTA_DELAY_SECONDS", 0)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Persisted:
    fake = Persisted()
    monkeypatch.setattr(chats, "append_message", fake.append_message)
    monkeypatch.setattr(citation_rows, "insert_citations", fake.insert_citations)
    return fake


@pytest.fixture
def thread() -> ThreadRef:
    return ThreadRef(id=uuid.uuid4(), user_id=uuid.uuid4(), title="Export controls")


@pytest.fixture
def retriever(monkeypatch: pytest.MonkeyPatch) -> FakeRetriever:
    """The orchestrator builds its own retriever; hand it ours instead."""
    fake = FakeRetriever()
    monkeypatch.setattr(orchestrator, "DocumentRetriever", lambda: fake)
    return fake


async def collect(user: CurrentUser, thread: ThreadRef, question: str) -> list[str]:
    return [
        frame
        async for frame in orchestrator.run_turn(
            user, thread, question=question, history=[]
        )
    ]


def events(frames: list[str]) -> list[dict[str, Any]]:
    return [
        json.loads(frame.removeprefix("data: "))
        for frame in frames
        if not frame.startswith("data: [DONE]")
    ]


def grounded_run(retriever: FakeRetriever) -> FunctionModel:
    chunk_id = retriever.passages[0].chunk_id
    return script(
        lambda info: search_call(query="export controls", ticker="NVDA"),
        lambda info: final(
            info,
            answer="Export controls cut China sales [1].",
            has_evidence=True,
            citations=[{"index": 1, "chunk_id": str(chunk_id), "quote": QUOTE}],
        ),
    )


def ungrounded_run() -> FunctionModel:
    return script(
        lambda info: search_call(query="export controls"),
        lambda info: final(
            info,
            answer="China sales fell [1].",
            has_evidence=True,
            citations=[{"index": 1, "chunk_id": str(uuid.uuid4()), "quote": QUOTE}],
        ),
    )


async def test_a_grounded_turn_streams_progress_then_answer_then_citations(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    with agent.override(model=grounded_run(retriever)):
        frames = await collect(user, thread, "Why did China sales fall?")

    kinds = [event["type"] for event in events(frames)]

    assert kinds[0] == "start"
    # Progress arrives before any answer text — that is what buys the wait.
    assert kinds.index("data-status") < kinds.index("text-start")
    assert kinds.index("text-end") < kinds.index("data-citation")
    assert kinds[-1] == "finish"
    assert frames[-1] == "data: [DONE]\n\n"


async def test_progress_parts_are_transient(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    """A reloaded thread shows the answer, not the search that found it."""
    with agent.override(model=grounded_run(retriever)):
        frames = await collect(user, thread, "Why did China sales fall?")

    statuses = [event for event in events(frames) if event["type"] == "data-status"]

    assert statuses
    assert all(status["transient"] is True for status in statuses)


async def test_the_progress_line_names_the_filing_being_searched(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    with agent.override(model=grounded_run(retriever)):
        frames = await collect(user, thread, "Why did China sales fall?")

    labels = [
        event["data"]["label"]
        for event in events(frames)
        if event["type"] == "data-status"
    ]

    assert labels == ["Searching NVDA…"]


async def test_deltas_reassemble_into_the_persisted_answer(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    with agent.override(model=grounded_run(retriever)):
        frames = await collect(user, thread, "Why did China sales fall?")

    streamed = "".join(
        str(event["delta"]) for event in events(frames) if event["type"] == "text-delta"
    )

    assert streamed == "Export controls cut China sales [1]."
    assert store.messages[0]["content"] == streamed


async def test_the_stored_message_carries_its_citation_parts(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    """Reload has to render what the live stream did, so parts go in verbatim."""
    with agent.override(model=grounded_run(retriever)):
        frames = await collect(user, thread, "Why did China sales fall?")

    streamed = [event for event in events(frames) if event["type"] == "data-citation"]
    stored = store.messages[0]["parts"]

    assert stored[0]["type"] == "text"
    assert stored[1:] == streamed


async def test_citations_are_persisted_with_the_quote_snapshotted(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    passage = retriever.passages[0]

    with agent.override(model=grounded_run(retriever)):
        await collect(user, thread, "Why did China sales fall?")

    assert store.citations == [
        {
            "message_id": store.messages[0]["message_id"],
            "citation_index": 1,
            "chunk_id": str(passage.chunk_id),
            "document_id": str(passage.document_id),
            "excerpt": QUOTE,
            "page": None,
            "section": "Item 1A. Risk Factors",
        }
    ]


async def test_the_streamed_message_id_is_the_one_it_is_stored_under(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    with agent.override(model=grounded_run(retriever)):
        frames = await collect(user, thread, "Why did China sales fall?")

    announced = events(frames)[0]["messageId"]

    assert str(store.messages[0]["message_id"]) == announced


async def test_an_ungrounded_answer_is_refused_not_shown(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    """The whole point: no unsupported prose reaches the analyst."""
    with agent.override(model=ungrounded_run()):
        frames = await collect(user, thread, "Why did China sales fall?")

    kinds = [event["type"] for event in events(frames)]

    assert "text-delta" not in kinds
    assert "error" in kinds
    # The stream still closes cleanly, so the client leaves its loading state.
    assert kinds[-1] == "finish"
    assert frames[-1] == "data: [DONE]\n\n"


async def test_a_refused_turn_writes_nothing(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    with agent.override(model=ungrounded_run()):
        await collect(user, thread, "Why did China sales fall?")

    assert store.messages == []
    assert store.citations == []


async def test_the_failure_message_is_written_for_an_analyst(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    """`errorText` reaches the screen verbatim, so it must read as product copy."""
    with agent.override(model=ungrounded_run()):
        frames = await collect(user, thread, "Why did China sales fall?")

    error = next(event for event in events(frames) if event["type"] == "error")

    assert "could not produce an answer" in error["errorText"]
    assert "citation" not in error["errorText"].lower()


async def test_a_refusal_streams_as_a_normal_answer(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    """No evidence is an answer, not an error — and it is persisted like one."""
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
        frames = await collect(user, thread, "What are Tesla's margins?")

    kinds = [event["type"] for event in events(frames)]

    assert "error" not in kinds
    assert "data-citation" not in kinds
    assert store.messages[0]["content"] == "These filings do not cover Tesla."
    assert store.citations == []


async def test_prior_turns_reach_the_model(
    user: CurrentUser, thread: ThreadRef, retriever: FakeRetriever, store: Persisted
) -> None:
    """Follow-ups like "and in 2024?" need the question that came before."""
    prompt_sizes: list[int] = []
    chunk_id = retriever.passages[0].chunk_id

    def respond(messages: list[Any], info: Any) -> Any:
        if not prompt_sizes:
            prompt_sizes.append(len(messages))
            return search_call(query="export controls", ticker="NVDA")
        return final(
            info,
            answer="Still falling [1].",
            has_evidence=True,
            citations=[{"index": 1, "chunk_id": str(chunk_id), "quote": QUOTE}],
        )

    history = [
        ui.UIMessage(role="user", parts=[{"type": "text", "text": "And in 2024?"}]),
        ui.UIMessage(role="assistant", parts=[{"type": "text", "text": "Sales fell."}]),
    ]

    with agent.override(model=FunctionModel(respond)):
        frames = [
            frame
            async for frame in orchestrator.run_turn(
                user, thread, question="And 2025?", history=history
            )
        ]

    assert frames
    # Two history messages plus this turn's prompt.
    assert prompt_sizes == [3]
