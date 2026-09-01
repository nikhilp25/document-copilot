"""The source passage behind a citation.

A `data-citation` part carries the quote and enough metadata to label a chip,
but not the text around it. That is what this route adds: the cited chunk in
full, plus the chunk either side of it in the filing. Clicking a claim then
shows the analyst the passage in context rather than replaying the one sentence
the chip already implied — which matters here, because chunk text can carry
table-serialisation noise that reads as nonsense when quoted alone.

The corpus is shared: every analyst sees the same filings, so this
authenticates the caller and then asks no further questions. Nothing
user-scoped is reachable through a chunk id. A chunk that is no longer in the
corpus — re-ingestion replaces chunk rows — is a 404 rather than an empty
panel, so the frontend can say the passage moved instead of showing a blank.
"""

import uuid
from collections.abc import Iterable
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.wire import WireModel
from app.auth.dependencies import CurrentUserDep
from app.retrieval.retriever import DocumentRetriever, SourcePassage

router = APIRouter(prefix="/passages", tags=["passages"])


class PassageResponse(WireModel):
    """One cited chunk and its neighbours, flattened for a single panel.

    Neighbours arrive as joined text rather than as passages of their own: the
    panel renders them as dimmed context around the quote, and their ids and
    scores are not something the analyst can act on.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID

    ticker: str
    company_name: str | None
    form_type: str
    fiscal_year: int
    filing_date: date
    accession_number: str
    source_url: str

    section: str | None
    # NULL corpus-wide — SEC HTML has no page breaks. Carried anyway so the
    # panel needs no change if a paginated source is ever ingested.
    page: int | None

    content: str
    context_before: str | None
    context_after: str | None


def get_retriever() -> DocumentRetriever:
    """The retriever this route reads through.

    A dependency rather than a module-level instance so a test can override it
    the same way it overrides the current user.
    """
    return DocumentRetriever()


RetrieverDep = Annotated[DocumentRetriever, Depends(get_retriever)]


@router.get("/{chunk_id}", response_model=PassageResponse)
async def read_passage(
    user: CurrentUserDep, chunk_id: uuid.UUID, retriever: RetrieverDep
) -> PassageResponse:
    """The cited passage, with one chunk of filing text either side of it."""
    window = await retriever.read_surrounding_chunks(chunk_id)
    cited = next((p for p in window if p.chunk_id == chunk_id), None)

    if cited is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That passage is no longer in the corpus.",
        )

    return PassageResponse(
        # `chunk_index` and `score` are retrieval's business, not the panel's.
        **cited.model_dump(exclude={"chunk_index", "score"}),
        context_before=_joined(p for p in window if p.chunk_index < cited.chunk_index),
        context_after=_joined(p for p in window if p.chunk_index > cited.chunk_index),
    )


def _joined(passages: Iterable[SourcePassage]) -> str | None:
    """Neighbour text as one block, or None when there is no neighbour.

    A blank paragraph between chunks because they are separate stretches of the
    filing, not a continuous paragraph — chunking split them on structure.
    """
    text = "\n\n".join(passage.content for passage in passages)
    return text or None
