"""The citation contract.

This is the product's one guarantee, so these tests are the ones that matter
most: each names the specific way an answer could mislead an analyst, and
asserts that the answer never reaches them.
"""

import uuid

from app.assistant.outputs import Citation, GroundedAnswer
from app.grounding.validator import violations
from app.retrieval.retriever import SourcePassage
from tests.grounding.conftest import passage

QUOTE = "Excessive or shifting export controls have already reduced our ability"


def answer(
    text: str,
    *,
    citations: list[Citation],
    has_evidence: bool = True,
) -> GroundedAnswer:
    return GroundedAnswer(answer=text, has_evidence=has_evidence, citations=citations)


def only(retrieved: dict[uuid.UUID, SourcePassage]) -> SourcePassage:
    return next(iter(retrieved.values()))


def test_a_well_cited_answer_passes(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    grounded = answer(
        "NVIDIA says export controls cut its China data centre sales [1].",
        citations=[Citation(index=1, chunk_id=only(retrieved).chunk_id, quote=QUOTE)],
    )

    assert violations(grounded, retrieved) == []


def test_citing_a_passage_that_was_never_retrieved_is_rejected(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    """The load-bearing rule: no citing documents the model was never shown."""
    invented = answer(
        "Apple's services margin expanded [1].",
        citations=[Citation(index=1, chunk_id=uuid.uuid4(), quote=QUOTE)],
    )

    problems = violations(invented, retrieved)

    assert len(problems) == 1
    assert "no search or read tool returned this turn" in problems[0]


def test_a_paraphrase_dressed_up_as_a_quote_is_rejected(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    """A plausible-sounding quote is exactly what an analyst cannot check."""
    reworded = answer(
        "Export controls hurt China sales [1].",
        citations=[
            Citation(
                index=1,
                chunk_id=only(retrieved).chunk_id,
                quote="Export controls have significantly harmed Chinese demand",
            )
        ],
    )

    problems = violations(reworded, retrieved)

    assert len(problems) == 1
    assert "does not appear" in problems[0]


def test_a_quote_wrapped_differently_from_the_source_still_passes() -> None:
    """Chunks carry table noise and hard wraps; the words are what must match."""
    source = passage("Item 7.  MD&A\nRevenue   grew\n13% year over year.")
    retrieved = {source.chunk_id: source}

    grounded = answer(
        "Revenue grew 13% [1].",
        citations=[
            Citation(
                index=1,
                chunk_id=source.chunk_id,
                quote="Revenue grew 13% year over year.",
            )
        ],
    )

    assert violations(grounded, retrieved) == []


def test_an_empty_quote_is_rejected(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    blank = answer(
        "Export controls matter [1].",
        citations=[Citation(index=1, chunk_id=only(retrieved).chunk_id, quote="  ")],
    )

    assert "empty quote" in violations(blank, retrieved)[0]


def test_a_marker_with_no_citation_is_rejected(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    """`[2]` next to a claim with nothing behind it reads as evidence."""
    dangling = answer(
        "Export controls cut sales [1]. Margins also fell [2].",
        citations=[Citation(index=1, chunk_id=only(retrieved).chunk_id, quote=QUOTE)],
    )

    problems = violations(dangling, retrieved)

    assert len(problems) == 1
    assert "markers [2]" in problems[0]


def test_a_citation_with_no_marker_is_rejected(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    """An unreferenced citation leaves the claim it supports unattributed."""
    unreferenced = answer(
        "Export controls cut sales.",
        citations=[Citation(index=1, chunk_id=only(retrieved).chunk_id, quote=QUOTE)],
    )

    problems = violations(unreferenced, retrieved)

    assert len(problems) == 1
    assert "never referenced" in problems[0]


def test_grouped_markers_are_accepted(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    """Models write `[1, 2]` unprompted; spending a retry on that helps nobody."""
    source = only(retrieved)
    grouped = answer(
        "Export controls cut China sales [1, 2].",
        citations=[
            Citation(index=1, chunk_id=source.chunk_id, quote=QUOTE),
            Citation(index=2, chunk_id=source.chunk_id, quote="Data Center compute"),
        ],
    )

    assert violations(grouped, retrieved) == []


def test_indexes_must_start_at_one_and_not_skip(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    source = only(retrieved)
    skipped = answer(
        "Export controls cut sales [1]. And again [3].",
        citations=[
            Citation(index=1, chunk_id=source.chunk_id, quote=QUOTE),
            Citation(index=3, chunk_id=source.chunk_id, quote="Data Center compute"),
        ],
    )

    problems = violations(skipped, retrieved)

    assert any("no gaps" in problem for problem in problems)


def test_repeated_indexes_are_rejected(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    source = only(retrieved)
    repeated = answer(
        "Export controls cut sales [1].",
        citations=[
            Citation(index=1, chunk_id=source.chunk_id, quote=QUOTE),
            Citation(index=1, chunk_id=source.chunk_id, quote="Data Center compute"),
        ],
    )

    assert any("repeats" in problem for problem in violations(repeated, retrieved))


def test_claiming_evidence_without_citing_any_is_rejected(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    """The confident uncited answer — the failure mode the brief calls fatal."""
    bare = answer("NVIDIA's data centre revenue tripled.", citations=[])

    problems = violations(bare, retrieved)

    assert len(problems) == 1
    assert "has_evidence=true but cited nothing" in problems[0]


def test_admitting_there_is_no_evidence_passes(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    """ "The corpus does not cover this" is a correct answer, not a failure."""
    refusal = answer(
        "The filings in this corpus do not cover Tesla.",
        citations=[],
        has_evidence=False,
    )

    assert violations(refusal, retrieved) == []


def test_denying_evidence_while_citing_it_is_rejected(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    contradictory = answer(
        "Not enough evidence [1].",
        citations=[Citation(index=1, chunk_id=only(retrieved).chunk_id, quote=QUOTE)],
        has_evidence=False,
    )

    assert (
        "has_evidence=false but included citations"
        in violations(contradictory, retrieved)[0]
    )


def test_every_fault_is_reported_at_once(
    retrieved: dict[uuid.UUID, SourcePassage],
) -> None:
    """One retry naming three faults beats three retries naming one each."""
    bad = answer(
        "Claim one [1]. Claim two [4].",
        citations=[
            Citation(index=1, chunk_id=uuid.uuid4(), quote="invented"),
            Citation(index=3, chunk_id=uuid.uuid4(), quote="also invented"),
        ],
    )

    assert len(violations(bad, retrieved)) > 2
