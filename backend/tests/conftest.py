"""Shared fixtures.

The chat routes are tested against an in-memory stand-in for
`app.database.chats` rather than a live Supabase. That keeps the fast suite
offline, and it keeps these tests about what the routes decide — who may touch
a thread, what gets persisted, in what order — which is the part that has bugs.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import CurrentUser, get_current_user
from app.database import chats
from app.database import citations as citation_rows
from app.database.models.chat_messages import MessageRole
from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    """Async tests run on asyncio only; the app never sees trio."""
    return "asyncio"


@pytest.fixture
def user() -> CurrentUser:
    return CurrentUser(
        id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        email="analyst@driftwood.test",
        access_token="valid-token",
    )


@pytest.fixture
def other_user() -> CurrentUser:
    return CurrentUser(
        id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        email="colleague@driftwood.test",
        access_token="other-token",
    )


class FakeChats:
    """An in-memory `app.database.chats`, honouring the same signatures."""

    def __init__(self) -> None:
        self.threads: dict[uuid.UUID, dict[str, Any]] = {}
        self.owners: dict[uuid.UUID, uuid.UUID] = {}
        self.messages: dict[uuid.UUID, list[dict[str, Any]]] = {}
        # Keyed by message id, the way `message_citations` hangs off a message.
        self.citations: dict[uuid.UUID, list[dict[str, Any]]] = {}
        # Records that `ensure_user_record` ran, so the FK prerequisite for
        # thread creation can be asserted rather than assumed.
        self.user_records: list[uuid.UUID] = []

    def add_thread(
        self, owner: uuid.UUID, *, title: str | None = None
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        thread_id = uuid.uuid4()
        thread = {
            "id": str(thread_id),
            "title": title,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        self.threads[thread_id] = thread
        self.owners[thread_id] = owner
        self.messages[thread_id] = []
        return thread

    async def find_thread(self, thread_id: uuid.UUID) -> chats.ThreadRef | None:
        if thread_id not in self.threads:
            return None
        return chats.ThreadRef(
            id=thread_id,
            user_id=self.owners[thread_id],
            title=self.threads[thread_id]["title"],
        )

    async def list_threads(self, user: CurrentUser) -> list[dict[str, Any]]:
        owned = [
            thread
            for thread_id, thread in self.threads.items()
            if self.owners[thread_id] == user.id
        ]
        return sorted(owned, key=lambda thread: thread["updated_at"], reverse=True)

    async def create_thread(
        self, user: CurrentUser, title: str | None = None
    ) -> dict[str, Any]:
        return self.add_thread(user.id, title=title)

    async def get_thread(
        self, user: CurrentUser, thread_id: uuid.UUID
    ) -> dict[str, Any]:
        return self.threads[thread_id]

    async def load_messages(
        self, user: CurrentUser, thread_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        return self.messages[thread_id]

    async def append_message(
        self,
        user: CurrentUser,
        thread_id: uuid.UUID,
        *,
        role: MessageRole,
        content: str,
        parts: list[dict[str, Any]] | None = None,
        message_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        message = {
            "id": str(message_id or uuid.uuid4()),
            "thread_id": str(thread_id),
            "role": role.value,
            "content": content,
            "parts": parts,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.messages[thread_id].append(message)
        self.threads[thread_id]["updated_at"] = message["created_at"]
        return message

    async def set_thread_title(
        self, user: CurrentUser, thread_id: uuid.UUID, title: str
    ) -> None:
        self.threads[thread_id]["title"] = title

    async def insert_citations(
        self,
        user: CurrentUser,
        message_id: uuid.UUID,
        citations: list[dict[str, Any]],
    ) -> None:
        self.citations[message_id] = citations


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeChats:
    fake = FakeChats()

    for name in (
        "find_thread",
        "list_threads",
        "create_thread",
        "get_thread",
        "load_messages",
        "append_message",
        "set_thread_title",
    ):
        monkeypatch.setattr(chats, name, getattr(fake, name))

    async def ensure_user_record(user: CurrentUser) -> None:
        fake.user_records.append(user.id)

    # Bound by name at import in the route module, so patch it there.
    monkeypatch.setattr("app.api.chat.ensure_user_record", ensure_user_record)

    monkeypatch.setattr(citation_rows, "insert_citations", fake.insert_citations)

    return fake


@pytest.fixture
def client() -> Iterator[TestClient]:
    """An unauthenticated client — requests carry no bearer token."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def signed_in(client: TestClient, user: CurrentUser) -> Iterator[TestClient]:
    """A client whose requests resolve to `user`, skipping Supabase Auth."""
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.clear()
