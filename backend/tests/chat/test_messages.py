"""AI SDK message conversion."""

import pytest

from app.chat.messages import UIMessage, assistant_parts, derive_title, text_of


def message(*parts: dict[str, object]) -> UIMessage:
    return UIMessage(id="msg-1", role="user", parts=list(parts))


def test_reads_text_across_several_parts() -> None:
    result = text_of(
        message(
            {"type": "text", "text": "Apple's "}, {"type": "text", "text": "margins"}
        )
    )

    assert result == "Apple's margins"


def test_ignores_parts_that_are_not_text() -> None:
    # A reasoning or tool part carries no question, but it must not break the
    # turn — the SDK adds part types faster than this backend consumes them.
    result = text_of(
        message(
            {"type": "step-start"},
            {"type": "text", "text": "What changed?"},
            {"type": "data-citation", "data": {"page": 42}},
        )
    )

    assert result == "What changed?"


def test_a_message_with_no_text_parts_is_empty() -> None:
    assert text_of(message({"type": "step-start"})) == ""


def test_assistant_parts_round_trip_through_text_of() -> None:
    answer = "Services revenue grew 13% year over year."

    restored = UIMessage(id="a", role="assistant", parts=assistant_parts(answer))

    assert text_of(restored) == answer


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        pytest.param(
            "What drove services growth?",
            "What drove services growth?",
            id="short questions are kept whole",
        ),
        pytest.param(
            "  What   drove\nservices growth?  ",
            "What drove services growth?",
            id="whitespace is collapsed",
        ),
        pytest.param(
            "Compare gross margin across Apple, Microsoft, and Nvidia for fiscal 2024",
            "Compare gross margin across Apple, Microsoft, and Nvidia…",
            id="long questions break on a word boundary",
        ),
    ],
)
def test_derive_title(question: str, expected: str) -> None:
    assert derive_title(question) == expected


def test_derive_title_handles_a_single_overlong_word() -> None:
    title = derive_title("x" * 200)

    assert len(title) == 61
    assert title.endswith("…")
