"""`message_citations` persistence — the evidence behind an assistant answer.

User-scoped like `chats.py`, not service-role: a citation hangs off one
analyst's message, so RLS should apply to it exactly as it does to the message.

Write-only for now. The transcript renders citations from the `data-citation`
parts stored on `chat_messages.parts`, which round-trip on their own; these
rows are the normalised record that makes an answer auditable later. A read
side belongs here the day something reads it.
"""

import uuid
from typing import Any

from app.auth.dependencies import CurrentUser
from app.database.supabase import user_client


async def insert_citations(
    user: CurrentUser, message_id: uuid.UUID, citations: list[dict[str, Any]]
) -> None:
    """Persist one answer's citations.

    Must run after the assistant message exists — `message_id` is a foreign key
    into `chat_messages`. Nothing to do when an answer legitimately cited
    nothing, which is what "the corpus does not cover this" looks like.
    """
    if not citations:
        return

    rows = [{"message_id": str(message_id), **citation} for citation in citations]

    client = await user_client(user.access_token)
    await client.table("message_citations").insert(rows).execute()
