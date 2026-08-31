"""Chunk row shaping and the pgvector literal format.

No Docling, no Supabase, no OpenAI — these cover the parts that decide what
lands in the table, which is where a silent corruption would hide.
"""

from typing import Any

import pytest

from app.database.chunks import to_vector_literal
from ingest.chunks import build_chunk_rows, section_of

DOCUMENT: dict[str, Any] = {
    "id": "3f6f2f0e-0f6a-4a1f-8f3a-1c2d3e4f5a6b",
    "accession_number": "0000320193-24-000123",
    "ticker": "AAPL",
    "company_name": "Apple Inc.",
    "cik": "0000320193",
    "form_type": "10-K",
    "filing_date": "2024-11-01",
    "report_date": "2024-09-28",
    "fiscal_year": 2024,
    "source_url": "https://www.sec.gov/Archives/edgar/data/320193/x/aapl.htm",
}


class FakeMeta:
    def __init__(self, headings: list[str] | None) -> None:
        self.headings = headings


class FakeChunk:
    """Stands in for a Docling `DocChunk` — the chunker only hands us these."""

    def __init__(self, text: str, headings: list[str] | None = None) -> None:
        self.text = text
        self.meta = FakeMeta(headings)


class FakeChunker:
    """`contextualize` prepends the heading trail, as HybridChunker's does."""

    def contextualize(self, chunk: FakeChunk) -> str:
        headings = chunk.meta.headings or []
        return "\n".join([*headings, chunk.text])


class FakeTokenizer:
    def count_tokens(self, text: str) -> int:
        return len(text.split())


@pytest.fixture
def rows() -> list[dict[str, Any]]:
    chunks = [
        FakeChunk("Total net sales were $391,035 million.", ["Item 7", "Net Sales"]),
        FakeChunk("Gross margin percentage was 46.2%.", ["Item 7", "Gross Margin"]),
    ]
    return build_chunk_rows(DOCUMENT, chunks, FakeChunker(), FakeTokenizer())


def test_chunk_index_is_gapless_and_ordered(rows: list[dict[str, Any]]) -> None:
    assert [row["chunk_index"] for row in rows] == [0, 1]


def test_content_is_contextualized_not_bare_text(rows: list[dict[str, Any]]) -> None:
    """The heading trail is embedded with the passage, so it must be stored."""
    assert rows[0]["content"] == (
        "Item 7\nNet Sales\nTotal net sales were $391,035 million."
    )


def test_token_count_describes_the_stored_content(rows: list[dict[str, Any]]) -> None:
    """Counting bare text would understate every chunk by its heading trail."""
    assert rows[0]["token_count"] == len(rows[0]["content"].split())


def test_filing_metadata_is_copied_onto_every_chunk(
    rows: list[dict[str, Any]],
) -> None:
    """Retrieval filters and cites from this without joining `source_documents`."""
    for row in rows:
        assert row["document_id"] == DOCUMENT["id"]
        assert row["metadata"]["ticker"] == "AAPL"
        assert row["metadata"]["fiscal_year"] == 2024
        assert row["metadata"]["accession_number"] == DOCUMENT["accession_number"]
        assert row["metadata"]["source_url"] == DOCUMENT["source_url"]


def test_section_records_the_heading_trail(rows: list[dict[str, Any]]) -> None:
    assert rows[0]["section"] == "Item 7 > Net Sales"
    assert rows[1]["section"] == "Item 7 > Gross Margin"


def test_page_is_null_because_markdown_has_no_pages(
    rows: list[dict[str, Any]],
) -> None:
    assert all(row["page"] is None for row in rows)


def test_section_is_null_when_a_chunk_has_no_headings() -> None:
    assert section_of(FakeChunk("Preamble text", [])) is None
    assert section_of(FakeChunk("Preamble text", None)) is None


def test_vector_literal_is_the_text_form_pgvector_parses() -> None:
    """A JSON array reaches a `vector` column as a Postgres array and fails."""
    assert to_vector_literal([0.1, -0.2, 0.0]) == "[0.1,-0.2,0.0]"


def test_vector_literal_keeps_full_float_precision() -> None:
    value = 0.123456789012345
    assert str(value) in to_vector_literal([value])
