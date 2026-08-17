"""Row shaping for corpus ingestion.

Pure mapping from a manifest entry to a `source_documents` row — no Supabase.
The bugs worth catching here are metadata ones: a filing landing under the year
it was filed instead of the year it reports on would misfile every citation.
"""

from typing import Any

from ingest.documents import build_document, markdown_path_for

FILING: dict[str, Any] = {
    "ticker": "AMZN",
    "cik": "0001018724",
    "form": "10-K",
    "filing_date": "2025-02-07",
    "report_date": "2024-12-31",
    "accession_number": "0001018724-25-000004",
    "primary_document": "amzn-20241231.htm",
    "source_url": "https://www.sec.gov/Archives/edgar/data/1018724/x/amzn.htm",
    "local_path": "2024\\amzn_10-k_2025-02-07_0001018724-25-000004.htm",
}


def test_build_document_maps_manifest_metadata() -> None:
    document = build_document(FILING, "# Amazon 10-K")

    assert document["accession_number"] == "0001018724-25-000004"
    assert document["ticker"] == "AMZN"
    assert document["company_name"] == "Amazon.com, Inc."
    assert document["cik"] == "0001018724"
    assert document["form_type"] == "10-K"
    assert document["filing_date"] == "2025-02-07"
    assert document["report_date"] == "2024-12-31"
    assert document["source_url"] == FILING["source_url"]
    assert document["markdown"] == "# Amazon 10-K"


def test_fiscal_year_follows_report_date_not_filing_date() -> None:
    """Amazon's FY2024 10-K is filed in 2025; analysts ask for it as 2024."""
    assert build_document(FILING, "")["fiscal_year"] == 2024


def test_fiscal_year_falls_back_to_filing_date() -> None:
    """EDGAR leaves `reportDate` empty on some filings."""
    filing = FILING | {"report_date": ""}
    document = build_document(filing, "")

    assert document["fiscal_year"] == 2025
    # NULL rather than an empty string, which Postgres rejects for a date.
    assert document["report_date"] is None


def test_unknown_ticker_ingests_without_a_company_name() -> None:
    document = build_document(FILING | {"ticker": "TSLA"}, "")

    assert document["ticker"] == "TSLA"
    assert document["company_name"] is None


def test_markdown_path_mirrors_the_downloads_tree() -> None:
    path = markdown_path_for(FILING["local_path"])

    assert path.suffix == ".md"
    assert path.name == "amzn_10-k_2025-02-07_0001018724-25-000004.md"
    assert path.parent.name == "2024"


def test_markdown_path_accepts_either_separator() -> None:
    """The manifest records whatever separator the downloading platform used."""
    windows = markdown_path_for("2024\\amzn_10-k.htm")
    posix = markdown_path_for("2024/amzn_10-k.htm")

    assert windows == posix
