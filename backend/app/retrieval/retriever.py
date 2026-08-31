"""Hybrid retrieval: a question in, ranked source passages out.

This is the whole of the product's ranking policy. The database returns two
independent rankings and knows nothing about how they combine; `fusion.py`
combines them and knows nothing about filings. Here is where those meet the
corpus's own shape — tickers, fiscal years, Item sections.

`DocumentRetriever`'s three methods are deliberately the three tools the
PydanticAI agent will be given in Phase 6: `search_filings`, `read_chunk` and
`read_surrounding_chunks`. Keeping them here rather than on the agent means the
retrieval contract is testable without an LLM in the loop, which is the point
of the split.
"""

import asyncio
import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel

from app import embeddings
from app.retrieval import queries
from app.retrieval.fusion import reciprocal_rank_fusion

# Fetched from each arm before fusion. Wide enough that a chunk the semantic
# arm buried at rank 40 can still be rescued by the lexical arm ranking it
# first, which is the case hybrid search exists for.
CANDIDATE_LIMIT = 50

# Returned after fusion. Ten 512-token passages is roughly 6k tokens of
# evidence — enough for an analyst to verify a claim, small enough that the
# agent can afford several searches in one turn.
DEFAULT_TOP_K = 10

# One chunk either side. Chunking split on document structure, so the immediate
# neighbours are the rest of the same Item; going wider mostly buys the next
# Item, which a fresh search would find better.
NEIGHBOR_RADIUS = 1


class SourcePassage(BaseModel):
    """A retrieved chunk with everything needed to cite it.

    A Pydantic model rather than the frozen dataclasses used elsewhere in the
    backend because this crosses the LLM tool boundary in Phase 6 and needs a
    JSON schema. It lives here, not in `assistant/`, so that the dependency
    runs agent -> retrieval and never back.

    `page` is on the model but NULL for the entire corpus: SEC HTML has no page
    breaks. Citations identify a passage by filing and Item section instead.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int

    ticker: str
    company_name: str | None
    form_type: str
    fiscal_year: int
    filing_date: date
    accession_number: str
    source_url: str

    section: str | None
    page: int | None
    content: str

    # The fused RRF score. None when the chunk was fetched by id rather than
    # ranked, because there is no ranking to report.
    score: float | None = None


class DocumentRetriever:
    """Query-to-passage retrieval over the ingested filing corpus.

    Stateless — it exists as a class because the agent's typed dependencies
    hold one, and because a fake with the same three methods is the natural
    seam for testing Phase 6 without a database.
    """

    async def search(
        self,
        query: str,
        *,
        ticker: str | None = None,
        fiscal_year: int | None = None,
        form_type: str | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[SourcePassage]:
        """Hybrid search: semantic + full text, fused, best first.

        Filters take one value each, not a list, because they are applied as
        JSONB containment (`metadata @> filter`) and containment cannot express
        `in`. That is a feature at the agent boundary: a question spanning five
        companies becomes five searches, each with its own budget of results,
        instead of one search where the loudest filer crowds out the rest.
        """
        filters = _containment_filter(
            ticker=ticker, fiscal_year=fiscal_year, form_type=form_type
        )

        # The query is embedded with the same model and width as the corpus —
        # `embed_text` is shared with ingestion for exactly that reason.
        embedding = await embeddings.embed_text(query)

        semantic, lexical = await asyncio.gather(
            queries.semantic_search(embedding, limit=CANDIDATE_LIMIT, filters=filters),
            queries.lexical_search(query, limit=CANDIDATE_LIMIT, filters=filters),
        )

        # Both arms return full rows, so fusion works on ids and the content is
        # already in hand — no second round trip to hydrate the winners.
        rows = {row["id"]: row for row in (*semantic, *lexical)}
        fused = reciprocal_rank_fusion(
            [[row["id"] for row in semantic], [row["id"] for row in lexical]]
        )

        # A cross-encoder reranker would slot in here, scoring the fused
        # candidates jointly against the query before the cut. Left out until
        # there is an eval set that can show it earns its latency.
        return [
            _passage(rows[chunk_id], score=score) for chunk_id, score in fused[:top_k]
        ]

    async def read_chunk(self, chunk_id: uuid.UUID) -> SourcePassage | None:
        """One passage by id, or None if it is no longer in the corpus."""
        row = await queries.chunk_by_id(chunk_id)
        return _passage(row) if row is not None else None

    async def read_surrounding_chunks(
        self, chunk_id: uuid.UUID, *, radius: int = NEIGHBOR_RADIUS
    ) -> list[SourcePassage]:
        """`chunk_id` and its neighbours in the same filing, in reading order.

        For the case where a retrieved passage starts mid-argument: the agent
        can widen the window on one hit instead of guessing at another query.
        Returns empty rather than raising if the chunk is gone.
        """
        anchor = await queries.chunk_by_id(chunk_id)
        if anchor is None:
            return []

        rows = await queries.neighbor_chunks(
            uuid.UUID(anchor["document_id"]), anchor["chunk_index"], radius=radius
        )
        return [_passage(row) for row in rows]


def _containment_filter(
    *, ticker: str | None, fiscal_year: int | None, form_type: str | None
) -> dict[str, Any]:
    """Build the `metadata @> filter` object, omitting unset filters.

    An empty object contains everything, so "no filter" needs no special case
    in the SQL.
    """
    filters: dict[str, Any] = {}

    if ticker is not None:
        filters["ticker"] = ticker
    if fiscal_year is not None:
        filters["fiscal_year"] = fiscal_year
    if form_type is not None:
        filters["form_type"] = form_type

    return filters


def _passage(row: dict[str, Any], *, score: float | None = None) -> SourcePassage:
    """Flatten a chunk row and its filing metadata into one passage.

    Ingestion copies filing metadata onto every chunk, so this needs no join.
    `section` is read from the column rather than the metadata copy of it: the
    column is what the neighbour query and the citation record both use.
    """
    metadata = row["metadata"]

    return SourcePassage(
        chunk_id=row["id"],
        document_id=row["document_id"],
        chunk_index=row["chunk_index"],
        ticker=metadata["ticker"],
        company_name=metadata["company_name"],
        form_type=metadata["form_type"],
        fiscal_year=metadata["fiscal_year"],
        filing_date=metadata["filing_date"],
        accession_number=metadata["accession_number"],
        source_url=metadata["source_url"],
        section=row["section"],
        page=row["page"],
        content=row["content"],
        score=score,
    )
