"""Translation between the AI SDK's wire format and our stored messages.

The frontend speaks the AI SDK UI message format, where a message is a role
plus an ordered list of typed *parts* rather than a string. We keep both forms:
`chat_messages.content` is the flattened text that retrieval, evaluation, and
logs read, and `chat_messages.parts` is the wire form stored verbatim so a
reloaded thread renders exactly like the live stream did.
"""

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

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


def assistant_parts(
    text: str, citations: Sequence[dict[str, Any]] = ()
) -> list[dict[str, Any]]:
    """The stored part list for an assistant reply built server-side.

    Citation parts go in verbatim, in the same order and the same shape the
    stream sent them, so a reloaded thread renders exactly what the analyst
    saw live. `text_of` filters to text parts, so they change nothing for
    anything that reads the message as prose.
    """
    return [{"type": "text", "text": text}, *citations]


def to_model_messages(messages: Sequence[UIMessage]) -> list[ModelMessage]:
    """Prior turns, in the form PydanticAI takes as `message_history`.

    Only the text survives. Citation and status parts were rendered for a
    human; replaying them would spend tokens teaching the model to imitate its
    own past citations instead of retrieving fresh ones. System messages are
    dropped too — the agent's instructions are re-applied on every run and are
    not the client's to override.
    """
    history: list[ModelMessage] = []

    for message in messages:
        text = text_of(message)
        if not text:
            continue

        if message.role == "user":
            history.append(ModelRequest([UserPromptPart(content=text)]))
        elif message.role == "assistant":
            history.append(ModelResponse([TextPart(content=text)]))

    return history


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
