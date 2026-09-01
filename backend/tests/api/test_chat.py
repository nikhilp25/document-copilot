"""Chat routes: authorization, history, and what a turn persists."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.assistant.agent import agent
from app.auth.dependencies import CurrentUser
from app.chat import orchestrator, streaming
from tests.assistant.conftest import (
    QUOTE,
    FakeRetriever,
    final,
    script,
    search_call,
)
from tests.conftest import FakeChats

# What the scripted model "answers" for every streaming test below.
ANSWER = "Services revenue grew on higher subscription pricing [1]."


def question(text: str) -> dict[str, object]:
    """A user turn in the AI SDK's wire format."""
    return {
        "id": "msg-1",
        "role": "user",
        "parts": [{"type": "text", "text": text}],
    }


def stream_events(body: str) -> list[dict[str, object]]:
    """The JSON events from an SSE body, dropping the [DONE] terminator."""
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


# --- authentication ---------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/chat/threads"),
        ("POST", "/chat/threads"),
        ("GET", f"/chat/threads/{uuid.uuid4()}"),
        ("POST", "/chat/stream"),
    ],
)
def test_rejects_requests_without_a_token(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, json={})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


# --- thread CRUD ------------------------------------------------------------


def test_lists_only_the_callers_threads(
    signed_in: TestClient, store: FakeChats, user: CurrentUser, other_user: CurrentUser
) -> None:
    mine = store.add_thread(user.id, title="Apple revenue mix")
    store.add_thread(other_user.id, title="Someone else's research")

    response = signed_in.get("/chat/threads")

    assert response.status_code == 200
    assert [thread["id"] for thread in response.json()] == [mine["id"]]


def test_creates_an_untitled_thread(
    signed_in: TestClient, store: FakeChats, user: CurrentUser
) -> None:
    response = signed_in.post("/chat/threads", json={})

    assert response.status_code == 201
    assert response.json()["title"] is None
    # Without the mirrored `public.users` row the insert would hit an FK.
    assert store.user_records == [user.id]


def test_loads_thread_history(
    signed_in: TestClient, store: FakeChats, user: CurrentUser
) -> None:
    thread = store.add_thread(user.id, title="Apple revenue mix")
    thread_id = uuid.UUID(thread["id"])
    store.messages[thread_id].append(
        {
            "id": str(uuid.uuid4()),
            "thread_id": thread["id"],
            "role": "user",
            "content": "What drove Apple's services growth?",
            "parts": [{"type": "text", "text": "What drove Apple's services growth?"}],
            "created_at": thread["created_at"],
        }
    )

    response = signed_in.get(f"/chat/threads/{thread_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["thread"]["title"] == "Apple revenue mix"
    assert [message["role"] for message in body["messages"]] == ["user"]
    # camelCase reaches the TypeScript client, not snake_case.
    assert "createdAt" in body["thread"]


# --- authorization ----------------------------------------------------------


def test_reading_another_users_thread_is_forbidden(
    signed_in: TestClient, store: FakeChats, other_user: CurrentUser
) -> None:
    thread = store.add_thread(other_user.id)

    response = signed_in.get(f"/chat/threads/{thread['id']}")

    assert response.status_code == 403


def test_streaming_into_another_users_thread_is_forbidden(
    signed_in: TestClient, store: FakeChats, other_user: CurrentUser
) -> None:
    thread = store.add_thread(other_user.id)

    response = signed_in.post(
        "/chat/stream",
        json={"threadId": thread["id"], "messages": [question("Anything?")]},
    )

    assert response.status_code == 403
    # The refusal has to land before anything is written to their thread.
    assert store.messages[uuid.UUID(thread["id"])] == []


@pytest.mark.parametrize("path", ["/chat/threads/{id}", "/chat/stream"])
def test_unknown_thread_is_not_found(
    signed_in: TestClient, store: FakeChats, path: str
) -> None:
    missing = uuid.uuid4()

    if path == "/chat/stream":
        response = signed_in.post(
            "/chat/stream",
            json={"threadId": str(missing), "messages": [question("Anything?")]},
        )
    else:
        response = signed_in.get(f"/chat/threads/{missing}")

    assert response.status_code == 404


# --- streaming a turn -------------------------------------------------------


@pytest.fixture(autouse=True)
def _instant_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the pacing delay so the suite doesn't wait on a cosmetic sleep."""
    monkeypatch.setattr(streaming, "_DELTA_DELAY_SECONDS", 0)


@pytest.fixture(autouse=True)
def _scripted_agent(monkeypatch: pytest.MonkeyPatch):
    """Stand in for OpenAI and the corpus.

    These tests are about what the route decides — who may stream, what gets
    persisted, in what order. The agent's own behaviour is covered in
    `tests/assistant`, and reaching a real model here would make the fast suite
    both slow and non-deterministic.
    """
    retriever = FakeRetriever()
    monkeypatch.setattr(orchestrator, "DocumentRetriever", lambda: retriever)
    chunk_id = retriever.passages[0].chunk_id

    model = script(
        lambda info: search_call(query="services growth", ticker="AAPL"),
        lambda info: final(
            info,
            answer=ANSWER,
            has_evidence=True,
            citations=[{"index": 1, "chunk_id": str(chunk_id), "quote": QUOTE}],
        ),
    )

    with agent.override(model=model):
        yield retriever


def test_stream_emits_a_well_formed_ui_message(
    signed_in: TestClient, store: FakeChats, user: CurrentUser
) -> None:
    thread = store.add_thread(user.id)

    response = signed_in.post(
        "/chat/stream",
        json={
            "threadId": thread["id"],
            "messages": [question("What drove Apple's services growth?")],
        },
    )

    assert response.status_code == 200
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.endswith("data: [DONE]\n\n")

    events = stream_events(response.text)
    types = [event["type"] for event in events]
    assert types[0] == "start"
    # Progress first, so the analyst sees the search before the answer.
    assert types[1] == "data-status"
    assert types[-2:] == ["data-citation", "finish"]
    assert types.count("text-delta") > 1

    # Every text event belongs to the message the stream announced. Citation
    # parts carry their own ids, which is what makes one replaceable in place.
    message_id = events[0]["messageId"]
    text_ids = {
        event["id"] for event in events if str(event["type"]).startswith("text-")
    }
    assert text_ids == {message_id}


def test_stream_deltas_reassemble_into_the_persisted_answer(
    signed_in: TestClient, store: FakeChats, user: CurrentUser
) -> None:
    thread = store.add_thread(user.id)
    thread_id = uuid.UUID(thread["id"])

    response = signed_in.post(
        "/chat/stream",
        json={
            "threadId": thread["id"],
            "messages": [question("Why did margins move?")],
        },
    )

    streamed = "".join(
        str(event["delta"])
        for event in stream_events(response.text)
        if event["type"] == "text-delta"
    )
    assistant = store.messages[thread_id][-1]

    assert assistant["role"] == "assistant"
    assert assistant["content"] == streamed
    # The id the client saw is the id the row was written under.
    assert assistant["id"] == stream_events(response.text)[0]["messageId"]


def test_turn_persists_both_messages_in_order(
    signed_in: TestClient, store: FakeChats, user: CurrentUser
) -> None:
    thread = store.add_thread(user.id)
    thread_id = uuid.UUID(thread["id"])

    signed_in.post(
        "/chat/stream",
        json={
            "threadId": thread["id"],
            "messages": [question("What drove Apple's services growth?")],
        },
    )

    stored = store.messages[thread_id]
    assert [message["role"] for message in stored] == ["user", "assistant"]
    assert stored[0]["content"] == "What drove Apple's services growth?"
    assert stored[0]["parts"] == [
        {"type": "text", "text": "What drove Apple's services growth?"}
    ]
    # Text first, then the citation parts the live stream sent, so a reloaded
    # thread renders exactly what the analyst saw.
    assert stored[1]["parts"][0] == {"type": "text", "text": stored[1]["content"]}
    assert [part["type"] for part in stored[1]["parts"][1:]] == ["data-citation"]


def test_a_turn_persists_the_evidence_behind_its_answer(
    signed_in: TestClient, store: FakeChats, user: CurrentUser
) -> None:
    thread = store.add_thread(user.id)
    thread_id = uuid.UUID(thread["id"])

    signed_in.post(
        "/chat/stream",
        json={
            "threadId": thread["id"],
            "messages": [question("What drove Apple's services growth?")],
        },
    )

    assistant = store.messages[thread_id][-1]
    citations = store.citations[uuid.UUID(assistant["id"])]

    assert [citation["citation_index"] for citation in citations] == [1]
    assert citations[0]["excerpt"] == QUOTE
    # SEC HTML has no page breaks, so a citation is located by its Item section.
    assert citations[0]["page"] is None
    assert citations[0]["section"] == "Item 1A. Risk Factors"


def test_first_turn_names_the_thread(
    signed_in: TestClient, store: FakeChats, user: CurrentUser
) -> None:
    thread = store.add_thread(user.id)

    signed_in.post(
        "/chat/stream",
        json={
            "threadId": thread["id"],
            "messages": [question("What drove Apple's services growth?")],
        },
    )

    assert store.threads[uuid.UUID(thread["id"])]["title"] == (
        "What drove Apple's services growth?"
    )


def test_later_turns_leave_the_title_alone(
    signed_in: TestClient, store: FakeChats, user: CurrentUser
) -> None:
    thread = store.add_thread(user.id, title="Apple revenue mix")

    signed_in.post(
        "/chat/stream",
        json={"threadId": thread["id"], "messages": [question("And in 2024?")]},
    )

    assert store.threads[uuid.UUID(thread["id"])]["title"] == "Apple revenue mix"


@pytest.mark.parametrize(
    "messages",
    [
        pytest.param([], id="no messages"),
        pytest.param(
            [
                {
                    "id": "a",
                    "role": "assistant",
                    "parts": [{"type": "text", "text": "hi"}],
                }
            ],
            id="last message is not the user's",
        ),
        pytest.param([question("   ")], id="empty question"),
    ],
)
def test_rejects_a_turn_with_no_question(
    signed_in: TestClient, store: FakeChats, user: CurrentUser, messages: list[dict]
) -> None:
    thread = store.add_thread(user.id)

    response = signed_in.post(
        "/chat/stream", json={"threadId": thread["id"], "messages": messages}
    )

    assert response.status_code == 422
    assert store.messages[uuid.UUID(thread["id"])] == []
