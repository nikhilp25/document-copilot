"""What the agent is required to return.

These field descriptions are not documentation. They are compiled into the
JSON schema the model is handed on every request, so they carry the citation
contract as directly as `instructions.md` does — a vague description here
weakens the product's one guarantee more than a vague comment ever could.
"""

import uuid

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """One passage backing one claim in the answer."""

    index: int = Field(
        description=(
            "1-based position of this citation. The answer text must carry a "
            "matching [n] marker, and they must run 1, 2, 3 with no gaps."
        )
    )
    chunk_id: uuid.UUID = Field(
        description=(
            "The `chunk_id` of a passage returned by a search or read tool "
            "during THIS conversation turn. Never invent one, and never reuse "
            "an id from an earlier turn."
        )
    )
    quote: str = Field(
        description=(
            "The exact sentence or sentences from that passage's `content` "
            "that support the claim, copied character for character. Do not "
            "paraphrase, summarise, or stitch together text from two places."
        )
    )


class GroundedAnswer(BaseModel):
    """A cited answer, or an honest statement that the corpus lacks one."""

    answer: str = Field(
        description=(
            "The answer for the analyst, in plain English, with a [n] marker "
            "after every factual claim naming the citation that supports it."
        )
    )
    has_evidence: bool = Field(
        description=(
            "True when the retrieved filings actually answer the question. "
            "False when they do not — then say what is missing and cite "
            "nothing. Never set this True to appear helpful."
        )
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description=(
            "Every passage the answer relies on, in the order the markers "
            "appear. Empty if and only if `has_evidence` is False."
        ),
    )
