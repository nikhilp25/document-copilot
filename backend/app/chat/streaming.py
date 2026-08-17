"""The AI SDK UI message stream protocol, server side.

The frontend's `useChat` transport reads Server-Sent Events where every `data:`
line is one JSON event describing part of the assistant's message:

    {"type": "start", "messageId": "..."}              the message begins
    {"type": "text-start", "id": "..."}                a text part opens
    {"type": "text-delta", "id": "...", "delta": "…"}  incremental text
    {"type": "text-end", "id": "..."}                  that part closes
    {"type": "finish"}                                 the message is complete
    [DONE]                                             stream terminator

Failures are `{"type": "error", "errorText": "..."}`. Citations will arrive in
Phase 6 as `data-citation` parts interleaved with the text deltas — the client
renders those as UI elements rather than prose, which is what makes a citation
chip clickable instead of a bracket in a sentence.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
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
# is genuinely exercised against the stub.
_DELTA_DELAY_SECONDS = 0.025
_WORDS_PER_DELTA = 3

_WORD = re.compile(r"\S+\s*")


def sse(event: dict[str, Any]) -> str:
    """One protocol event as an SSE frame."""
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


def stub_answer(question: str) -> str:
    """The Phase 3 placeholder reply.

    It states the grounding contract rather than inventing an answer, so the
    stub never looks like a real one during development.
    """
    return (
        "Retrieval isn't wired up yet, so there are no filings behind this "
        "answer and I won't invent one. Once the corpus is ingested, this turn "
        f"will answer “{question}” with citations to specific filings, pages, "
        "and sections."
    )


async def text_stream(text: str, *, message_id: str) -> AsyncIterator[str]:
    """Emit `text` as a complete AI SDK message, a few words at a time."""
    yield sse({"type": "start", "messageId": message_id})
    yield sse({"type": "text-start", "id": message_id})

    for delta in _deltas(text):
        yield sse({"type": "text-delta", "id": message_id, "delta": delta})
        await asyncio.sleep(_DELTA_DELAY_SECONDS)

    yield sse({"type": "text-end", "id": message_id})
    yield sse({"type": "finish"})
    yield "data: [DONE]\n\n"


def _deltas(text: str) -> list[str]:
    """Split into word groups, keeping the whitespace that separates them."""
    words = _WORD.findall(text)
    return [
        "".join(words[index : index + _WORDS_PER_DELTA])
        for index in range(0, len(words), _WORDS_PER_DELTA)
    ]
