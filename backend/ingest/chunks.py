"""Chunk the converted corpus into `document_chunks`, without embeddings.

Run from `backend/`, after `ingest.documents`:

    uv run python -m ingest.chunks

Docling's HybridChunker does the work. It starts from the HierarchicalChunker's
structural split — one chunk per document element, keeping the heading trail —
then splits anything oversized for the tokenizer and merges undersized peers
that share headings. Passing the *embedding model's own* tokenizer is the point:
chunk boundaries then line up with what OpenAI will actually charge for.

Embeddings are a separate pass (`ingest.embed`). Rows land here with a NULL
embedding, which is the schema's marker for "chunked but not yet embedded".

Docling is a dev dependency, so nothing under `app/` may import this module.
"""

from __future__ import annotations

import asyncio
import gc
import json
import re
import sys
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import tiktoken
from docling.chunking import HybridChunker
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.base import BaseChunk
from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.io import DocumentStream

from app.config import settings
from app.database.chunks import (
    count_chunks,
    count_missing_embeddings,
    delete_chunks_for_document,
    insert_chunks,
)
from app.database.documents import list_source_documents
from app.database.supabase import close_http_client
from ingest.documents import MANIFEST_PATH, markdown_path_for

# Well under the model's 8192-token ceiling, on purpose. A retrieved passage is
# evidence an analyst has to read and verify, and a whole page of filing text
# averaged into one vector retrieves vaguely. Raising this cuts the row count
# (and storage) proportionally.
MAX_TOKENS = 512

# Re-chunk from scratch instead of skipping filings that already have chunks.
# Deletes their existing chunks, which discards their embeddings too.
REPLACE_EXISTING = False

# Stop after this many filings. Set to 1 to prove the pipeline on one 10-K
# before committing to the whole corpus; None runs everything.
DOCUMENT_LIMIT: int | None = None


def build_tokenizer() -> OpenAITokenizer:
    return OpenAITokenizer(
        tokenizer=tiktoken.encoding_for_model(settings.openai_embedding_model),
        max_tokens=MAX_TOKENS,
    )


def build_chunker(tokenizer: OpenAITokenizer) -> HybridChunker:
    # `merge_peers` packs adjacent undersized elements sharing a heading, which
    # keeps a filing's many one-line rows from each becoming their own chunk.
    # `repeat_table_header` (on by default) re-emits the header row when a wide
    # financial table has to be split, so the second half still says what its
    # columns mean.
    return HybridChunker(tokenizer=tokenizer, merge_peers=True)


# A 10-K item heading: "Item 7A." and a title, at the start of a line. The
# title is required — Microsoft repeats a bare "Item 1" as a running page
# header on every page, and those are not headings. The length cap keeps prose
# cross-references ("Item 1A. Risk Factors of this Annual Report describes...")
# from being promoted.
_ITEM_HEADING = re.compile(
    r"^item\s+(\d{1,2}[A-C]?)\s*[.:]?\s+(\S.{2,110})$", re.IGNORECASE
)


def _heading_candidate(line: str) -> str:
    """The text of `line` as a heading would read, or the line unchanged.

    Amazon's filings put item headings inside a table row, and the HTML→
    Markdown conversion repeats each cell across the row's colspan:

        | Item 1A. | Item 1A. | Item 1A. | Risk Factors | Risk Factors |

    Collapsing repeats in order recovers "Item 1A. Risk Factors".
    """
    if not line.startswith("|"):
        return line.strip()

    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    unique = list(dict.fromkeys(cell for cell in cells if cell))
    return " ".join(unique)


def promote_item_headings(markdown: str) -> str:
    """Mark 10-K item headings as Markdown headings.

    SEC filers style headings with `<div>`/`<p>` and CSS rather than `<h1>`–
    `<h6>`, so Docling's HTML backend finds no structure and the converted
    Markdown has none either. That leaves the chunker with a flat wall of text:
    no heading trail to keep chunks together, nothing for `contextualize()` to
    prepend, and no section to cite. Restoring the one heading level a 10-K
    reliably has gives all three back.
    """
    promoted = []

    for line in markdown.splitlines():
        candidate = _heading_candidate(line)
        match = _ITEM_HEADING.match(candidate)

        # Table-of-contents rows link to the body; the body heading is the one
        # worth marking, and marking both would open the same section twice.
        if match and "](#" not in candidate:
            promoted.append(f"## Item {match.group(1)}. {match.group(2)}")
        else:
            promoted.append(line)

    return "\n".join(promoted)


_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return all(_SEPARATOR_CELL.match(cell) for cell in cells if cell) and any(cells)


def _strip_empty_columns(block: list[str]) -> list[str]:
    """Drop columns that are empty in every row of one Markdown table."""
    rows = [_split_row(line) for line in block]
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    content_rows = [row for row in rows if not _is_separator(row)]
    keep = [
        column for column in range(width) if any(row[column] for row in content_rows)
    ]

    # Nothing but layout scaffolding — the table said nothing at all.
    if not keep:
        return []

    return ["| " + " | ".join(row[column] for column in keep) + " |" for row in rows]


def strip_empty_table_columns(markdown: str) -> str:
    """Remove layout-only columns from the filing's tables.

    SEC filings lay pages out with tables, so the conversion carries columns
    that are empty in every row. The chunker serializes a table cell by cell —
    an empty one becomes `Label, = .` — so these columns reach the embedding as
    padding: they were roughly a third of the corpus's tokens, diluting every
    vector and displacing real text from the 512-token budget.

    Only wholly-empty columns go. A column with any value anywhere is data.
    """
    output: list[str] = []
    block: list[str] = []

    for line in [*markdown.splitlines(), ""]:
        if line.lstrip().startswith("|"):
            block.append(line)
            continue

        if block:
            output.extend(_strip_empty_columns(block))
            block = []
        output.append(line)

    return "\n".join(output[:-1])


def load_markdown_document(markdown_path: Path) -> DoclingDocument:
    """Parse a converted filing back into the structure the chunker needs.

    The chunkers walk a `DoclingDocument`, not raw text — headings, tables and
    list structure are exactly what they split on.
    """
    markdown = markdown_path.read_text(encoding="utf-8")
    markdown = promote_item_headings(strip_empty_table_columns(markdown))
    source = DocumentStream(
        name=markdown_path.name, stream=BytesIO(markdown.encode("utf-8"))
    )

    converter = DocumentConverter(allowed_formats=[InputFormat.MD])
    return converter.convert(source).document


def section_of(chunk: BaseChunk) -> str | None:
    """The chunk's heading trail, e.g. `Item 7A > Interest Rate Risk`."""
    headings = chunk.meta.headings or []
    return " > ".join(headings) or None


def build_chunk_rows(
    document: dict[str, Any],
    chunks: list[BaseChunk],
    chunker: HybridChunker,
    tokenizer: OpenAITokenizer,
) -> list[dict[str, Any]]:
    """Shape one filing's chunks into `document_chunks` rows.

    `content` holds the *contextualized* text — the passage with its heading
    trail prepended — and that same string is what gets embedded. Storing
    anything else here would leave the generated `search_vector` describing
    different text than the vector does, and hybrid retrieval would have its
    two halves disagree.
    """
    filing_metadata = {
        "ticker": document["ticker"],
        "company_name": document["company_name"],
        "cik": document["cik"],
        "form_type": document["form_type"],
        "fiscal_year": document["fiscal_year"],
        "filing_date": document["filing_date"],
        "accession_number": document["accession_number"],
        "source_url": document["source_url"],
    }

    rows = []
    for index, chunk in enumerate(chunks):
        content = chunker.contextualize(chunk=chunk)
        section = section_of(chunk)

        rows.append(
            {
                "document_id": document["id"],
                "chunk_index": index,
                "content": content,
                "token_count": tokenizer.count_tokens(content),
                # Markdown carries no page provenance — Docling's HTML backend
                # emits no page breaks, so there is nothing to inherit. Section
                # headings are what citations will have to point at.
                "page": None,
                "section": section,
                "metadata": filing_metadata | {"section": section},
            }
        )

    return rows


def chunk_filing(
    document: dict[str, Any],
    markdown_path: Path,
    chunker: HybridChunker,
    tokenizer: OpenAITokenizer,
) -> list[dict[str, Any]]:
    """Parse and chunk one filing, releasing the parsed document afterwards."""
    dl_doc = load_markdown_document(markdown_path)
    chunks = list(chunker.chunk(dl_doc=dl_doc))
    rows = build_chunk_rows(document, chunks, chunker, tokenizer)

    # A parsed 10-K is large enough that holding several at once exhausted
    # memory during the HTML conversion pass. Same discipline here.
    del dl_doc, chunks
    gc.collect()

    return rows


def markdown_paths_by_accession() -> dict[str, Path]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        filing["accession_number"]: markdown_path_for(filing["local_path"])
        for filing in manifest["filings"]
    }


async def chunk_corpus(document_limit: int | None = None) -> tuple[int, int]:
    """Chunk ingested filings that don't have chunks yet.

    `document_limit` counts filings actually chunked, not filings looked at, so
    a run picks up where the last one stopped instead of re-examining the same
    finished documents.
    """
    tokenizer = build_tokenizer()
    chunker = build_chunker(tokenizer)
    markdown_paths = markdown_paths_by_accession()

    documents = await list_source_documents()
    chunked = written = 0

    for document in documents:
        if document_limit is not None and chunked >= document_limit:
            break

        label = (
            f"{document['ticker']} {document['form_type']} FY{document['fiscal_year']}"
        )
        document_id = uuid.UUID(document["id"])
        existing = await count_chunks(document_id)

        if existing and not REPLACE_EXISTING:
            print(f"Skipping {label} ({existing} chunks already)")
            continue

        if existing:
            await delete_chunks_for_document(document_id)

        rows = chunk_filing(
            document, markdown_paths[document["accession_number"]], chunker, tokenizer
        )
        inserted = await insert_chunks(rows)

        tokens = sum(row["token_count"] for row in rows)
        print(f"Chunked {label}: {inserted} chunks, {tokens:,} tokens")
        chunked += 1
        written += inserted

    return chunked, written


async def main() -> int:
    # An optional count of filings to chunk before exiting. Parsing a 10-K is
    # memory-hungry and Python returns little of it to the OS, so on a machine
    # short on RAM the reliable way to run the corpus is one filing per
    # process: `for /l %i in (1,1,25) do python -m ingest.chunks 1`.
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else DOCUMENT_LIMIT

    chunked, written = await chunk_corpus(limit)
    pending = await count_missing_embeddings()
    await close_http_client()

    print(f"\nChunked {chunked} filing(s) into {written:,} rows.")
    print(f"{pending:,} chunk(s) awaiting embeddings — run `python -m ingest.embed`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
