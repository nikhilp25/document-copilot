# Data

Local data artifacts for development live here.

- `downloads/` holds raw source files fetched from SEC EDGAR, grouped by year.
- `markdown/` holds the same filings converted to Markdown, mirroring the
  `downloads/` tree exactly (`downloads/2024/aapl_10-k_….htm` →
  `markdown/2024/aapl_10-k_….md`).
- Both trees are gitignored because the corpus can get large.
- Fetch a sample corpus with `uv run data/download.py`
- Convert it to Markdown with `uv run --project backend data/convert.py`

Then load the corpus into Supabase from `backend/`:

```bash
uv run python -m ingest.documents
```

That writes one `source_documents` row per filing, Markdown included, keyed by
EDGAR accession number — re-running updates in place instead of duplicating.

Then chunk and embed, also from `backend/`:

```bash
uv run python -m ingest.chunks   # Docling HybridChunker → document_chunks
uv run python -m ingest.embed    # OpenAI embeddings for rows still NULL
```

The two passes are deliberately separate. Chunking is free and repeatable;
embedding costs money, so it selects on `embedding IS NULL` and can be
interrupted and resumed without paying twice. Set `CHUNK_LIMIT = 1` in
`ingest/embed.py` to prove the chain on a single chunk first.

Parsing a 10-K needs well over a gigabyte, and Python hands little of it back
between filings. On a machine without several free gigabytes, chunk one filing
per process instead — `ingest.chunks` takes an optional count and skips filings
that already have chunks, so this resumes on its own:

```powershell
for ($i = 1; $i -le 25; $i++) { uv run python -m ingest.chunks 1 }
```

`convert.py` uses [Docling](https://docling-project.github.io/docling/), which is
a dev dependency of the backend — hence `--project backend`. Re-runs skip filings
that already have a `.md` output, so an interrupted run resumes where it stopped
(set `SKIP_EXISTING = False` in the script to force a full re-convert).
