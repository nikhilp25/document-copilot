"""The AI SDK stream protocol emitter."""

import json

import pytest

from app.chat.streaming import STREAM_HEADERS, sse, stub_answer, text_stream


@pytest.fixture(autouse=True)
def _instant_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.chat.streaming._DELTA_DELAY_SECONDS", 0)


async def collect(text: str, *, message_id: str = "msg-1") -> list[str]:
    return [frame async for frame in text_stream(text, message_id=message_id)]


def test_sse_frames_are_single_line_and_double_terminated() -> None:
    frame = sse({"type": "text-delta", "delta": "a\nb"})

    assert frame.endswith("\n\n")
    # A raw newline inside the payload would split one event into two.
    assert frame.count("\n") == 2
    assert json.loads(frame.removeprefix("data: "))["delta"] == "a\nb"


def test_protocol_version_header_is_declared() -> None:
    # The transport discards a stream that doesn't announce the protocol.
    assert STREAM_HEADERS["x-vercel-ai-ui-message-stream"] == "v1"


@pytest.mark.anyio
async def test_stream_opens_and_closes_the_message() -> None:
    frames = await collect("Margins expanded on services mix.")
    events = [
        json.loads(frame.removeprefix("data: "))
        for frame in frames
        if not frame.startswith("data: [DONE]")
    ]

    assert [event["type"] for event in events][:2] == ["start", "text-start"]
    assert [event["type"] for event in events][-2:] == ["text-end", "finish"]
    assert frames[-1] == "data: [DONE]\n\n"


@pytest.mark.anyio
async def test_deltas_reassemble_into_the_original_text() -> None:
    text = "Services revenue grew 13% year over year, per the FY2024 10-K."

    frames = await collect(text)
    deltas = [
        json.loads(frame.removeprefix("data: "))
        for frame in frames
        if '"text-delta"' in frame
    ]

    assert len(deltas) > 1
    assert "".join(delta["delta"] for delta in deltas) == text


@pytest.mark.anyio
async def test_empty_text_still_produces_a_complete_message() -> None:
    frames = await collect("")

    types = [
        json.loads(frame.removeprefix("data: "))["type"]
        for frame in frames
        if not frame.startswith("data: [DONE]")
    ]
    assert types == ["start", "text-start", "text-end", "finish"]


def test_stub_answer_refuses_to_invent_and_echoes_the_question() -> None:
    answer = stub_answer("What drove Apple's services growth?")

    # The stub must never read like a real grounded answer during development.
    assert "What drove Apple's services growth?" in answer
    assert "no filings" in answer
