"""Chat thread and message persistence.

Everything here runs through the *analyst's* Supabase client, so RLS filters
every statement and an authorization bug in route code leaks nothing. The rows
are still filtered by `user_id` explicitly — RLS is the backstop, not the plan.

`find_thread` is the one exception, and the reason is in its docstring.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from supabase import AsyncClient

from app.auth.dependencies import CurrentUser
from app.database.models.chat_messages import MessageRole
from app.database.supabase import service_client, user_client

_THREAD_COLUMNS = "id, title, created_at, updated_at"
_MESSAGE_COLUMNS = "id, thread_id, role, content, parts, created_at"


@dataclass(frozen=True, slots=True)
class ThreadRef:
    """Just enough of a thread to authorize a request against it."""

    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None


def _now() -> str:
    # `updated_at` has an `onupdate` in the model, but that only fires on
    # SQLAlchemy writes and these go through PostgREST. Every write that should
    # reorder the sidebar has to say so itself.
    return datetime.now(UTC).isoformat()


async def find_thread(thread_id: uuid.UUID) -> ThreadRef | None:
    """Look up a thread regardless of who owns it, or None if there is none.

    Deliberately privileged. A user-scoped read of someone else's thread comes
    back empty, which cannot tell "not yours" apart from "not there" — and the
    routes have to answer 403 for the first and 404 for the second. Nothing
    from this row reaches the response body; it only decides the status code.
    """
    client = await service_client()
    response = (
        await client.table("chat_threads")
        .select("id, user_id, title")
        .eq("id", str(thread_id))
        .maybe_single()
        .execute()
    )

    if response is None:
        return None

    row = response.data
    return ThreadRef(
        id=uuid.UUID(row["id"]),
        user_id=uuid.UUID(row["user_id"]),
        title=row["title"],
    )


async def list_threads(user: CurrentUser) -> list[dict[str, Any]]:
    """This analyst's threads, most recently active first."""
    client = await user_client(user.access_token)
    response = (
        await client.table("chat_threads")
        .select(_THREAD_COLUMNS)
        .eq("user_id", str(user.id))
        .order("updated_at", desc=True)
        .execute()
    )
    return response.data


async def create_thread(user: CurrentUser, title: str | None = None) -> dict[str, Any]:
    """Open a new thread. Title stays NULL until the first turn names it."""
    client = await user_client(user.access_token)
    response = (
        await client.table("chat_threads")
        .insert({"user_id": str(user.id), "title": title})
        .execute()
    )
    return response.data[0]


async def get_thread(user: CurrentUser, thread_id: uuid.UUID) -> dict[str, Any]:
    """One thread of this analyst's. Callers authorize before asking."""
    client = await user_client(user.access_token)
    response = (
        await client.table("chat_threads")
        .select(_THREAD_COLUMNS)
        .eq("id", str(thread_id))
        .eq("user_id", str(user.id))
        .single()
        .execute()
    )
    return response.data


async def load_messages(
    user: CurrentUser, thread_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every message in a thread, oldest first."""
    client = await user_client(user.access_token)
    response = (
        await client.table("chat_messages")
        .select(_MESSAGE_COLUMNS)
        .eq("thread_id", str(thread_id))
        .order("created_at")
        .execute()
    )
    return response.data


async def append_message(
    user: CurrentUser,
    thread_id: uuid.UUID,
    *,
    role: MessageRole,
    content: str,
    parts: list[dict[str, Any]] | None = None,
    message_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Persist one turn and bump the thread so the sidebar reorders.

    `message_id` lets the caller fix the id before the row exists. The stream
    announces the assistant's message id in its opening event, and the client's
    copy has to match the stored one for citations to resolve later.
    """
    row: dict[str, Any] = {
        "thread_id": str(thread_id),
        "role": role.value,
        "content": content,
        "parts": parts,
    }
    if message_id is not None:
        row["id"] = str(message_id)

    client = await user_client(user.access_token)
    response = await client.table("chat_messages").insert(row).execute()

    await _touch_thread(client, user, thread_id)
    return response.data[0]


async def set_thread_title(user: CurrentUser, thread_id: uuid.UUID, title: str) -> None:
    """Name a thread. Callers only do this while the title is still NULL."""
    client = await user_client(user.access_token)
    await (
        client.table("chat_threads")
        .update({"title": title, "updated_at": _now()})
        .eq("id", str(thread_id))
        .eq("user_id", str(user.id))
        .execute()
    )


async def _touch_thread(
    client: AsyncClient, user: CurrentUser, thread_id: uuid.UUID
) -> None:
    await (
        client.table("chat_threads")
        .update({"updated_at": _now()})
        .eq("id", str(thread_id))
        .eq("user_id", str(user.id))
        .execute()
    )
