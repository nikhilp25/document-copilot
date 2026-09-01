"""Fixtures for the citation contract tests."""

import uuid
from datetime import date

import pytest

from app.retrieval.retriever import SourcePassage

PASSAGE_TEXT = (
    "Item 1A. Risk Factors\n"
    "Excessive or shifting export controls have already reduced our ability\n"
    "to sell Data Center compute products to customers in China."
)


def passage(content: str = PASSAGE_TEXT) -> SourcePassage:
    """A retrieved passage, shaped exactly as `DocumentRetriever` returns one."""
    return SourcePassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=7,
        ticker="NVDA",
        company_name="NVIDIA Corporation",
        form_type="10-K",
        fiscal_year=2025,
        filing_date=date(2025, 2, 26),
        accession_number="0001045810-25-000023",
        source_url="https://www.sec.gov/Archives/edgar/data/1045810/nvda.htm",
        section="Item 1A. Risk Factors",
        page=None,
        content=content,
        score=0.4,
    )


@pytest.fixture
def retrieved() -> dict[uuid.UUID, SourcePassage]:
    """One passage the tools returned this turn."""
    found = passage()
    return {found.chunk_id: found}
