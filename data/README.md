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

`convert.py` uses [Docling](https://docling-project.github.io/docling/), which is
a dev dependency of the backend — hence `--project backend`. Re-runs skip filings
that already have a `.md` output, so an interrupted run resumes where it stopped
(set `SKIP_EXISTING = False` in the script to force a full re-convert).
