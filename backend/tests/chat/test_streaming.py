"""The AI SDK stream protocol emitter."""

import json
import uuid

import pytest

from app.chat.streaming import (
    STREAM_HEADERS,
    answer_stream,
    citation_part,
    error_part,
    sse,
    start_part,
    status_part,
)

MESSAGE_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")

CHIP = {
    "chunkId": "66666666-6666-4666-8666-666666666666",
    "ticker": "NVDA",
    "section": "Item 1A. Risk Factors",
    "page": None,
}


@pytest.fixture(autouse=True)
def _instant_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.chat.streaming._DELTA_DELAY_SECONDS", 0)


async def collect(text: str, **kwargs: object) -> list[str]:
    return [
        frame async for frame in answer_stream(text, message_id=MESSAGE_ID, **kwargs)
    ]


def parse(frames: list[str]) -> list[dict[str, object]]:
    return [
        json.loads(frame.removeprefix("data: "))
        for frame in frames
        if not frame.startswith("data: [DONE]")
    ]


def test_sse_frames_are_single_line_and_double_terminated() -> None:
    frame = sse({"type": "text-delta", "delta": "a\nb"})

    assert frame.endswith("\n\n")
    # A raw newline inside the payload would split one event into two.
    assert frame.count("\n") == 2
    assert json.loads(frame.removeprefix("data: "))["delta"] == "a\nb"


def test_protocol_version_header_is_declared() -> None:
    # The transport discards a stream that doesn't announce the protocol.
    assert STREAM_HEADERS["x-vercel-ai-ui-message-stream"] == "v1"


def test_start_announces_the_id_the_message_will_be_stored_under() -> None:
    assert start_part(MESSAGE_ID) == {"type": "start", "messageId": str(MESSAGE_ID)}


def test_status_parts_are_transient() -> None:
    """Transient parts never enter `message.parts`, so progress leaves no trace."""
    part = status_part("Searching NVDA…")

    assert part["type"] == "data-status"
    assert part["transient"] is True


def test_citation_parts_are_not_transient_and_carry_a_stable_id() -> None:
    """Citations have to survive a reload, and re-sending one must not duplicate."""
    part = citation_part(2, CHIP, quote="Export controls reduced our ability")

    assert part["type"] == "data-citation"
    assert part["id"] == "citation-2"
    assert "transient" not in part
    assert part["data"]["index"] == 2
    assert part["data"]["ticker"] == "NVDA"
    assert part["data"]["quote"] == "Export controls reduced our ability"


def test_error_parts_carry_the_text_the_analyst_will_read() -> None:
    # `describeError` on the frontend falls through to this string verbatim.
    assert error_part("Try a narrower question.") == {
        "type": "error",
        "errorText": "Try a narrower question.",
    }


@pytest.mark.anyio
async def test_stream_opens_and_closes_the_text_part() -> None:
    kinds = [event["type"] for event in parse(await collect("Margins expanded."))]

    assert kinds[0] == "text-start"
    assert kinds[-2:] == ["text-end", "finish"]


@pytest.mark.anyio
async def test_deltas_reassemble_into_the_original_text() -> None:
    text = "Services revenue grew 13% year over year, per the FY2024 10-K."

    frames = await collect(text)
    deltas = [event for event in parse(frames) if event["type"] == "text-delta"]

    assert len(deltas) > 1
    assert "".join(str(delta["delta"]) for delta in deltas) == text
    assert frames[-1] == "data: [DONE]\n\n"


@pytest.mark.anyio
async def test_citations_follow_the_text_they_support() -> None:
    """They are only known once the whole answer has been validated."""
    citation = citation_part(1, CHIP, quote="Export controls")

    kinds = [
        event["type"]
        for event in parse(await collect("Sales fell [1].", citations=[citation]))
    ]

    assert kinds.index("text-end") < kinds.index("data-citation")
    assert kinds[-1] == "finish"


@pytest.mark.anyio
async def test_empty_text_still_produces_a_complete_message() -> None:
    kinds = [event["type"] for event in parse(await collect(""))]

    assert kinds == ["text-start", "text-end", "finish"]
