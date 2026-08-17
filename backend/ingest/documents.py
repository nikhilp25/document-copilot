"""Load the converted filing corpus into `source_documents`.

Run from `backend/` after `data/download.py` and `data/convert.py`:

    uv run python -m ingest.documents

Filing metadata comes from `data/downloads/manifest.json`; the text comes from
the matching Markdown file. Re-runs are safe — rows are keyed by EDGAR
accession number and upserted, so this is the idempotent step Phase 4 asks for.

Chunking and embedding are separate passes; this one only lands whole filings.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path, PurePosixPath
from typing import Any

from app.database.documents import list_source_documents, upsert_source_document
from app.database.supabase import close_http_client

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "downloads" / "manifest.json"
MARKDOWN_DIR = REPO_ROOT / "data" / "markdown"

# EDGAR reports these on the submissions endpoint, but `manifest.json` doesn't
# record them. Unknown tickers ingest with a NULL company name rather than
# failing — the column is nullable and the ticker already identifies the filer.
COMPANY_NAMES = {
    "AAPL": "Apple Inc.",
    "AMZN": "Amazon.com, Inc.",
    "GOOGL": "Alphabet Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
}


def markdown_path_for(local_path: str) -> Path:
    """Locate the Markdown that `data/convert.py` wrote for a downloaded filing.

    `local_path` is recorded by whichever platform ran the download, so it may
    arrive with either separator.
    """
    relative = PurePosixPath(local_path.replace("\\", "/"))
    return (MARKDOWN_DIR / relative).with_suffix(".md")


def build_document(filing: dict[str, Any], markdown: str) -> dict[str, Any]:
    """Shape one manifest entry plus its Markdown into a `source_documents` row."""
    # EDGAR leaves `reportDate` empty on some filings; the filing date is the
    # only date always present.
    report_date = filing["report_date"] or None

    return {
        "accession_number": filing["accession_number"],
        "ticker": filing["ticker"],
        "company_name": COMPANY_NAMES.get(filing["ticker"]),
        "cik": filing["cik"],
        "form_type": filing["form"],
        "filing_date": filing["filing_date"],
        "report_date": report_date,
        # The year the filing *reports on*, not the year it was filed: Amazon's
        # FY2024 10-K is filed in February 2025 and analysts ask for it as 2024.
        "fiscal_year": int((report_date or filing["filing_date"])[:4]),
        "source_url": filing["source_url"],
        "markdown": markdown,
    }


async def ingest_corpus() -> tuple[int, int]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    ingested = missing = 0

    for filing in manifest["filings"]:
        markdown_path = markdown_path_for(filing["local_path"])

        if not markdown_path.exists():
            print(f"  MISSING {markdown_path.name} — run data/convert.py first")
            missing += 1
            continue

        document = build_document(filing, markdown_path.read_text(encoding="utf-8"))
        await upsert_source_document(document)
        print(
            f"Ingested {document['ticker']} {document['form_type']} "
            f"FY{document['fiscal_year']} ({len(document['markdown']):,} chars)"
        )
        ingested += 1

    return ingested, missing


async def main() -> int:
    ingested, missing = await ingest_corpus()
    documents = await list_source_documents()
    await close_http_client()

    print(f"\nIngested {ingested} filing(s), {missing} missing Markdown.")
    print(f"source_documents now holds {len(documents)} row(s).")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
