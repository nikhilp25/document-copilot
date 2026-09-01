"""The AI SDK UI message stream protocol, server side.

The frontend's `useChat` transport reads Server-Sent Events where every `data:`
line is one JSON event describing part of the assistant's message:

    {"type": "start", "messageId": "..."}              the message begins
    {"type": "data-status", ..., "transient": true}    progress, not content
    {"type": "text-start", "id": "..."}                a text part opens
    {"type": "text-delta", "id": "...", "delta": "…"}  incremental text
    {"type": "text-end", "id": "..."}                  that part closes
    {"type": "data-citation", "id": "...", "data": {}} one cited passage
    {"type": "error", "errorText": "..."}              a controlled failure
    {"type": "finish"}                                 the message is complete
    [DONE]                                             stream terminator

Shapes are checked against `pydantic_ai.ui.vercel_ai.response_types`, which
types this protocol out inside a dependency we already have. We emit the frames
by hand rather than through its `VercelAIAdapter` because the adapter streams
the model's output as it arrives, and this product may not show a word of an
answer before its citations have been validated.

Two part kinds carry everything Phase 6 added:

- `data-status` is **transient**: the AI SDK delivers it to `onData` but never
  adds it to `message.parts`, so progress shows during a run and leaves no
  trace in the transcript. Exactly right for "Searching NVDA FY2025…".
- `data-citation` is not transient and carries a stable id, so it lands in
  `parts`, gets stored on `chat_messages.parts`, and reappears verbatim when
  the thread is reloaded.
"""

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

# The transport rejects a stream that does not announce the protocol version.
STREAM_HEADERS = {
    "x-vercel-ai-ui-message-stream": "v1",
    "Cache-Control": "no-cache",
    # Proxies buffer responses by default, which collapses a token-by-token
    # stream into a single delivery at the end and defeats the whole endpoint.
    "X-Accel-Buffering": "no",
}

# Fast enough to feel live, slow enough that the frontend's streaming indicator
# is genuinely exercised.
_DELTA_DELAY_SECONDS = 0.025
_WORDS_PER_DELTA = 3

_WORD = re.compile(r"\S+\s*")


def sse(event: dict[str, Any]) -> str:
    """One protocol event as an SSE frame."""
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


def start_part(message_id: uuid.UUID) -> dict[str, Any]:
    """Opens the message and fixes the id the client will store it under."""
    return {"type": "start", "messageId": str(message_id)}


def status_part(label: str) -> dict[str, Any]:
    """Progress while the agent works.

    Transient, so it never becomes part of the saved message. A reloaded thread
    should show the answer, not the search that found it.
    """
    return {"type": "data-status", "data": {"label": label}, "transient": True}


def citation_part(index: int, passage: dict[str, Any], quote: str) -> dict[str, Any]:
    """One citation, carrying everything a chip and a passage panel need.

    The id is stable and derived from the index so a re-sent part replaces its
    predecessor rather than duplicating it.
    """
    return {
        "type": "data-citation",
        "id": f"citation-{index}",
        "data": {"index": index, "quote": quote, **passage},
    }


def error_part(text: str) -> dict[str, Any]:
    """A failure the analyst is meant to read.

    `errorText` reaches the screen verbatim — the frontend's `describeError`
    has no mapping for stream errors and falls through to the message. So this
    is product copy, not a diagnostic.
    """
    return {"type": "error", "errorText": text}


async def answer_stream(
    text: str,
    *,
    message_id: uuid.UUID,
    citations: Sequence[dict[str, Any]] = (),
) -> AsyncIterator[str]:
    """Emit a validated answer and its citations, then close the message.

    Citations follow the text rather than interleaving with it. They are only
    known once the whole answer has been validated, and the markers in the
    prose are what tie a claim to its chip.
    """
    identifier = str(message_id)

    yield sse({"type": "text-start", "id": identifier})

    for delta in _deltas(text):
        yield sse({"type": "text-delta", "id": identifier, "delta": delta})
        await asyncio.sleep(_DELTA_DELAY_SECONDS)

    yield sse({"type": "text-end", "id": identifier})

    for citation in citations:
        yield sse(citation)

    yield sse({"type": "finish"})
    yield "data: [DONE]\n\n"


def _deltas(text: str) -> list[str]:
    """Split into word groups, keeping the whitespace that separates them."""
    words = _WORD.findall(text)
    return [
        "".join(words[index : index + _WORDS_PER_DELTA])
        for index in range(0, len(words), _WORDS_PER_DELTA)
    ]
