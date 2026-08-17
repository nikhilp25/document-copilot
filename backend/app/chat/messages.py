"""Translation between the AI SDK's wire format and our stored messages.

The frontend speaks the AI SDK UI message format, where a message is a role
plus an ordered list of typed *parts* rather than a string. We keep both forms:
`chat_messages.content` is the flattened text that retrieval, evaluation, and
logs read, and `chat_messages.parts` is the wire form stored verbatim so a
reloaded thread renders exactly like the live stream did.
"""

from typing import Any, Literal

from pydantic import BaseModel

# Long enough to tell two research threads apart in the sidebar, short enough
# not to wrap.
_TITLE_LIMIT = 60


class UIMessage(BaseModel):
    """One message as the AI SDK sends it.

    `parts` is deliberately untyped. The SDK grows part types faster than this
    product consumes them, and a strict union here would reject a thread that
    renders perfectly well in the browser. The parts we actually read — text —
    are picked out by `text_of`; the rest ride along to storage untouched.
    """

    id: str | None = None
    role: Literal["user", "assistant", "system"]
    parts: list[dict[str, Any]]


def text_of(message: UIMessage) -> str:
    """The message's plain text, ignoring parts that aren't text."""
    return "".join(
        part.get("text", "") for part in message.parts if part.get("type") == "text"
    ).strip()


def assistant_parts(text: str) -> list[dict[str, Any]]:
    """The stored part list for an assistant reply built server-side."""
    return [{"type": "text", "text": text}]


def derive_title(question: str) -> str:
    """Name a thread after the question that opened it.

    Threads arrive titleless and the sidebar needs something to show. Cutting
    on a word boundary keeps the truncation from landing mid-word.
    """
    collapsed = " ".join(question.split())

    if len(collapsed) <= _TITLE_LIMIT:
        return collapsed

    clipped = collapsed[:_TITLE_LIMIT].rsplit(" ", 1)[0]
    # A single word longer than the limit has no boundary to fall back to.
    return f"{clipped or collapsed[:_TITLE_LIMIT]}…"
