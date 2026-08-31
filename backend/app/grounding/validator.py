"""The citation contract, as a function.

Deliberately free of pydantic-ai and of I/O. The rule this enforces — every
claim is backed by a passage that was actually retrieved this turn — is the
product, so it has to be checkable in a unit test without a model, a network,
or a database.

The strings it returns are read twice: once by the model, as the retry prompt
that gives it a chance to correct itself, and once by us in a log when it
fails anyway. They are written as instructions to the model for that reason.
"""

import re
import uuid
from collections.abc import Mapping

from app.assistant.outputs import Citation, GroundedAnswer
from app.retrieval.retriever import SourcePassage

# `[1]`, and also `[1, 2]` — models reach for the grouped form unprompted, and
# rejecting it would spend a retry on punctuation instead of on grounding.
_MARKER = re.compile(r"\[([\d\s,]+)\]")


def violations(
    answer: GroundedAnswer, retrieved: Mapping[uuid.UUID, SourcePassage]
) -> list[str]:
    """Every way this answer breaks the citation contract.

    Empty means the answer may be shown to an analyst. All problems are
    collected rather than short-circuited: one round trip that names three
    faults beats three round trips that each name one.
    """
    problems: list[str] = []

    problems.extend(_evidence_matches_citations(answer))
    problems.extend(_indexes_are_a_clean_sequence(answer.citations))

    for citation in answer.citations:
        problems.extend(_quote_is_real(citation, retrieved))

    problems.extend(_markers_match_citations(answer))

    return problems


def _evidence_matches_citations(answer: GroundedAnswer) -> list[str]:
    """`has_evidence` is a claim about the citations; hold it to that."""
    if answer.has_evidence and not answer.citations:
        return [
            (
                "You set has_evidence=true but cited nothing. Either cite the "
                "passages the answer rests on, or set has_evidence=false and "
                "say what the filings do not cover."
            )
        ]
    if not answer.has_evidence and answer.citations:
        return [
            (
                "You set has_evidence=false but included citations. If the "
                "filings do support an answer, set has_evidence=true."
            )
        ]
    return []


def _indexes_are_a_clean_sequence(citations: list[Citation]) -> list[str]:
    """1, 2, 3 with no gaps and no repeats — the markers depend on it."""
    indexes = [citation.index for citation in citations]

    if sorted(indexes) != list(range(1, len(indexes) + 1)):
        return [
            (
                f"Citation indexes must run 1 to {len(indexes)} with no gaps "
                f"or repeats; you used {sorted(indexes)}."
            )
        ]
    return []


def _quote_is_real(
    citation: Citation, retrieved: Mapping[uuid.UUID, SourcePassage]
) -> list[str]:
    """The passage was retrieved this turn, and the quote is really in it."""
    passage = retrieved.get(citation.chunk_id)

    if passage is None:
        # The load-bearing check. Anything else here is a quality problem;
        # this one is the model citing a document it was never shown.
        return [
            (
                f"Citation [{citation.index}] uses chunk_id "
                f"{citation.chunk_id}, which no search or read tool returned "
                "this turn. Cite only passages you retrieved, and search again "
                "if you need more."
            )
        ]

    if not citation.quote.strip():
        return [f"Citation [{citation.index}] has an empty quote."]

    if _collapsed(citation.quote) not in _collapsed(passage.content):
        return [
            (
                f"Citation [{citation.index}] quotes text that does not appear "
                f"in chunk {citation.chunk_id}. Copy the supporting sentence "
                "from that passage exactly rather than rewording it."
            )
        ]

    return []


def _markers_match_citations(answer: GroundedAnswer) -> list[str]:
    """Every marker has a citation, and every citation has a marker."""
    marked = {
        int(index)
        for match in _MARKER.findall(answer.answer)
        for index in match.split(",")
        if index.strip()
    }
    cited = {citation.index for citation in answer.citations}

    problems = []

    if unsupported := sorted(marked - cited):
        problems.append(
            f"The answer carries markers {unsupported} with no matching "
            "citation. Every [n] must name a citation you listed."
        )
    if unused := sorted(cited - marked):
        problems.append(
            f"Citations {unused} are never referenced in the answer. Put a [n] "
            "marker after the claim each one supports."
        )

    return problems


def _collapsed(text: str) -> str:
    """Whitespace-insensitive form, for comparing a quote to its source.

    Chunks carry Markdown table serialisation and reconstructed headings, so
    line breaks and runs of spaces differ from what a model copies out. The
    words and their order still have to match exactly.
    """
    return " ".join(text.split())
