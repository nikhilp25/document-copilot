# Document Copilot — implementation checklist

Work top to bottom. Each phase unlocks the next. Check items off as you go.

> **Status (2026-08-19): Phases 0–6 complete. Phase 7 (trust UI) is next.**
>
> The product now does the thing it exists to do. Ask a question, watch the
> filings being searched, get an answer where every claim carries a `[n]` marker
> backed by a verbatim quote from a passage retrieved on that turn — and get a
> refusal, not a guess, when the corpus does not cover the question.
>
> The corpus is ingested (25 filings, 9,617 embedded chunks), `app/retrieval/`
> ranks it, and `app/assistant/` + `app/grounding/` turn that into cited
> answers. `stub_answer()` is gone. 137 backend tests pass offline
> (`uv run pytest -m "not integration"`), plus 15 against the live model and
> corpus (`uv run pytest -m integration`).
>
> What is missing is the last mile of trust: citations stream and persist, but
> `message-bubble.tsx` still renders text parts only, so an analyst cannot yet
> click a claim and see the passage. That is Phase 7, and it is now unblocked.

## Where to start: backend, frontend, or both?

**Start with foundation, then backend-led vertical slices.**

| Order | Why |
| ----- | --- |
| 1. Supabase + sample data | Everything persists here; you need a project and a corpus to test against. |
| 2. Backend schema + migrations | Auth, chat, retrieval, and citations all depend on the data model. |
| 3. Thin vertical slices | Wire auth, then a stubbed chat stream, then real RAG — each slice touches frontend + backend together. |
| 4. Frontend in parallel (lightly) | Scaffold the SPA early, but don't build citation UI or chat polish until the backend can return real grounded answers. |

The critical path is **data model → ingestion → retrieval → LLM → citations**. The frontend is mostly a streaming chat shell with auth and citation display — it shouldn't get far ahead of working APIs.

---

## Phase 0 — Prerequisites & foundation

- [x] Install toolchain: Python 3.12+, `uv`, Node 20+, `pnpm` (see [README](../README.md))
- [x] Create Supabase project and collect credentials ([supabase-setup](guides/supabase-setup.md))
- [x] Create OpenAI API key (needed from Phase 6 onward)
- [x] Set `USER_AGENT` in `data/download.py` and download sample 10-K corpus:
  ```bash
  uv run data/download.py
  ```
- [x] Confirm `data/downloads/manifest.json` lists AAPL, MSFT, NVDA, AMZN, GOOGL filings (2021–2025)

---

## Phase 1 — Backend scaffold & database

Goal: a running FastAPI service with a migrated Supabase schema.

- [x] Init backend deps and project layout ([backend-setup](guides/backend-setup.md))
- [x] `app/config.py` — settings module, fail fast on missing env vars
- [x] `app/main.py` — FastAPI app, CORS, health check (`GET /health`)
- [x] SQLAlchemy models in `app/database/models/`:
  - [x] `users`
  - [x] `source_documents`
  - [x] `document_chunks` (embedding + generated `tsvector`)
  - [x] `chat_threads`
  - [x] `chat_messages`
  - [x] `message_citations`
- [x] Alembic init + first migration:
  - [x] `create extension if not exists vector`
  - [x] `vector(1536)` embedding column
  - [x] generated `tsvector` column on chunks
  - [x] HNSW index (vector) + GIN index (full-text)
  - [x] RLS policies (users see only their own chats)
- [x] `uv run alembic upgrade head` against Supabase direct connection
- [x] `app/database/supabase.py` — user-scoped and service-role clients
- [x] Verify: `uv run uvicorn app.main:app --reload` → health check returns 200

---

## Phase 2 — Auth (full stack)

Goal: analysts can sign in with email; backend rejects unauthenticated requests.

**Backend**

- [x] `app/auth/dependencies.py` — verify `Authorization: Bearer <supabase_jwt>`, expose `get_current_user`
- [x] Reject missing/expired tokens with `401` before any chat or retrieval work

**Frontend**

- [x] Scaffold Vite + React + TypeScript + Tailwind + shadcn ([frontend-setup](guides/frontend-setup.md))
- [x] `src/lib/env.ts` — validate `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
- [x] `src/lib/supabase.ts` — browser Supabase client
- [x] `src/lib/http.ts` + `src/lib/api.ts` — fetch wrapper with automatic bearer token
- [x] Sign-in / sign-up pages (email only, no SSO)
- [x] Protected routes — redirect unauthenticated users to login
- [x] Verify: sign up, sign in, token reaches backend on a test authenticated endpoint

---

## Phase 3 — Chat shell (vertical slice, stubbed)

Goal: end-to-end chat UI streaming from FastAPI, no real retrieval yet.

**Backend**

- [x] Chat thread CRUD: list threads, create thread, load message history
- [x] `POST /chat/stream` — accepts AI SDK message format, streams a stubbed assistant reply
- [x] Persist user + assistant messages to `chat_messages` after stream completes
- [x] `403` when user accesses another user's thread

**Frontend**

- [x] React Router: login, chat list, chat thread routes
- [x] AI SDK chat primitives pointed at `POST /chat/stream` with Supabase bearer token
- [x] Thread sidebar (past conversations)
- [x] Basic message list + input + streaming indicator
- [x] Verify: create thread, send message, see streamed stub response, reload and see history

---

## Phase 4 — Ingestion pipeline

Goal: SEC filings in the corpus are parsed, chunked, embedded, and stored in Supabase.

- [x] `ingest/` scripts (or CLI entrypoint) for one-off corpus loading — `ingest/documents.py`
- [x] HTML → normalized Markdown extraction — `data/convert.py` (Docling) writes
      `data/markdown/`, mirroring the `downloads/` tree. Page numbers are *not*
      preserved: Docling's HTML backend emits no page breaks, so `document_chunks.page`
      stays NULL and citations will have to cite sections instead.
- [x] Chunking strategy — Docling `HybridChunker` at 512 tokens, counted with the
      embedding model's own `cl100k_base` tokenizer (`ingest/chunks.py`). No fixed
      overlap: chunks split on document structure and `merge_peers` packs
      undersized peers sharing a heading.
      Chunk index, section, ticker, filing type and year are all stored. `page`
      is the one column left NULL — see "Known gaps" below; it is a property of
      the source HTML, not work left to do.
- [x] Write `source_documents` rows with filing metadata from `manifest.json` — all 25 filings loaded
- [x] Write `document_chunks` rows with text + metadata — 9,617 chunks, filing
      metadata copied onto each so retrieval needn't join `source_documents`
- [x] OpenAI embedding generation → store `vector(1536)` per chunk — 100% embedded
      (`ingest/embed.py`), ~4.3M tokens, ~$0.09 on `text-embedding-3-small`
- [x] Generated `tsvector` populated for full-text search — 0 chunks missing it
- [x] Idempotent re-run — `source_documents` upserts on `accession_number`;
      chunking skips filings that already have chunks; embedding selects on
      `embedding IS NULL`, so an interrupted run resumes without paying twice
- [x] Unit tests: chunking logic, metadata extraction, Markdown normalization
      (`tests/ingest/`, 27 tests, offline)
- [x] Run ingestion on full sample corpus (25 filings × 5 companies)
- [x] Verify: 9,617/9,617 embedded at 1536 dims, 25/25 documents, no gaps in
      `chunk_index`, 97.3% with a section. Semantic spot-checks return the right
      filer *and* the right item — "NVIDIA export controls to China" →
      NVDA FY2025 Item 1A at 0.776 cosine.

### Known gaps carried into Phase 5

- `page` is NULL corpus-wide. SEC HTML has no page breaks, so citations must
  cite Item sections, not page numbers.
- Section headings are reconstructed, not parsed: filers style headings with CSS
  instead of `<h1>`–`<h6>`, so `ingest/chunks.py` promotes `Item N.` lines back
  to Markdown headings. Microsoft's letter-spaced titles survive mangled
  ("Item 1. B USINESS") — the item number is right, the title text is cosmetic.
- Some chunks still carry table serialization noise (`label, = .`) where a
  column holds a value in at least one row. Wholly-empty columns are stripped;
  partial ones can't be without losing data.

---

## Phase 5 — Retrieval

Goal: a user question returns ranked, relevant source passages.

- [x] `retrieval/queries.py` — pgvector semantic search over `document_chunks`,
      through the `match_chunks_semantic` Postgres function. PostgREST cannot
      express `order by embedding <=> $1`, so both ranked arms are SQL functions
      added by migration `eb1fd84894ef` and called over `rpc()` — no second
      database connection, everything stays on the existing Supabase client.
- [x] `retrieval/queries.py` — Postgres full-text search over `search_vector`,
      through `match_chunks_lexical`. Terms are ORed by `analyst_tsquery`, not
      ANDed: every tsquery builder Postgres ships requires *every* term, so a
      whole analyst question matched nothing and this arm was silently dead.
      ORing them is also what makes it a stand-in for BM25, which scores a bag
      of words; `ts_rank_cd` then ranks by coverage.
- [x] `retrieval/fusion.py` — Reciprocal Rank Fusion in Python, `k=60`
- [x] `retrieval/retriever.py` — query → fused ranked passages + neighbor chunks.
      `DocumentRetriever.search` / `read_chunk` / `read_surrounding_chunks` are
      deliberately the three tools Phase 6 hands the agent. 50 candidates per
      arm, top 10 out. Filters (`ticker`, `fiscal_year`, `form_type`) take one
      value each because they apply as JSONB containment, which has no `in` —
      cross-company questions become one search per company.
- [x] Unit tests: fusion ranking, query assembly (mock DB) — `tests/retrieval/`,
      28 tests, offline
- [x] Integration test (optional, `@pytest.mark.integration`): real query against
      ingested corpus — 10 tests, first use of the marker
- [x] Verify: test queries from [client-brief](client-brief.md) return relevant
      chunks. Q3 → NVDA Item 7 MD&A and Item 1A on data center demand; Q4 with
      `ticker="MSFT"` → the Azure/cloud sections across FY2022–25; Q7 with
      `ticker="AAPL"` → "Substantially all of the Company's manufacturing" in
      Item 1A across four years. A full search is ~1.5s including the query
      embedding, with both arms running concurrently.

### Notes for Phase 6

- No reranker. The reference pipeline this follows ends with a cross-encoder,
  which is the single biggest accuracy win — but it is a new dependency and a
  third API key, and there is no eval set yet to show it earns its latency.
  `retriever.py` marks where it slots in.
- `SourcePassage` lives in `retrieval/retriever.py`, not `assistant/outputs.py`,
  so the dependency runs agent → retrieval and never back. `GroundedAnswer`
  should import it.
- `app/config.py` still has no chat-model setting; Phase 6 needs one.

---

## Phase 6 — LLM agent & grounding

Goal: grounded answers with enforced citations — the core product contract.

- [x] `assistant/instructions.md` — product contract, kept as Markdown so it can
      be edited and diffed as prose rather than buried in a Python string
- [x] PydanticAI agent with typed deps (`DocumentAgentDeps`) and output
      (`GroundedAnswer`), on `gpt-5.5` via the new `OPENAI_CHAT_MODEL` setting
- [x] Agent tools: `search_filings`, `read_chunk`, `read_surrounding_chunks` —
      one line each over Phase 5's `DocumentRetriever`. Every tool routes its
      results through `deps.remember`, building the ledger of what the model
      was actually shown; that ledger is what makes grounding a membership test
      instead of a judgement call.
- [x] `chat/orchestrator.py` — one turn: agent → validate → stream → persist
- [x] `grounding/validator.py` — a pure function, no pydantic-ai and no I/O.
      Wired as an `@agent.output_validator` that raises `ModelRetry`, so a
      fixable citation costs one more request rather than the whole turn, and
      re-run afterwards as the fail-closed gate.
- [x] `chat/streaming.py` — `data-citation` parts after the text, transient
      `data-status` parts during the run, `error` parts on failure;
      `stub_answer()` deleted
- [x] Replaced the `stub_answer()` call in `app/api/chat.py::stream_turn` with
      the orchestrator
- [x] Persist `message_citations` linked to assistant messages
      (`app/database/citations.py`), quote snapshotted as the excerpt
- [x] Unit tests: citation validation, grounding enforcement, message conversion
      — 41 new offline tests. The agent ones run the *real* agent against a
      `FunctionModel`, so the grounding contract is tested, not mocked away.
- [x] Verify against [client-brief example questions](client-brief.md#example-analyst-questions):
  - [x] Answers cite specific filings and **sections** — `page` is NULL
        corpus-wide, so a citation is located by its Item
  - [x] Questions the corpus cannot answer come back `has_evidence=false` with
        no citations (verified against a company outside the corpus)
  - [x] Question 10 (generative AI margins) declines the causal claim and cites
        only what the filings literally say

### How a turn streams, and why

The analyst sees progress immediately and prose only after it has been checked:

```
 4.4s  data-status   Searching NVDA…            (transient — never persisted)
 …     data-status   Searching NVDA 2024…
68.4s  text-start / text-delta …                (validated answer)
68.4s  data-citation ×10                        (persisted with the message)
68.4s  finish / [DONE]
```

Streaming raw model tokens would be faster to first word, but the analyst could
read a claim that validation then retracts — the failure the brief calls fatal.
So the text is gated and the wait is covered by progress parts instead.

### Notes carried into Phase 7

- The full turn above took **68s** on a real cross-section question with ten
  searches. Progress starts at ~4s so nobody stares at a blank panel, but this
  is the number to watch in Phase 8's latency review. The knobs are the model's
  reasoning effort and `CANDIDATE_LIMIT`.
- Citation excerpts inherit the Phase 4 table-serialisation noise: one citation
  above quotes `Direct Customer A, = Direct Customer A.` verbatim, because that
  is genuinely what the chunk says. The model is behaving correctly; the chunk
  is not. Worth a passage-panel design that shows surrounding context.
- The frontend needs no change to *receive* citations — they already stream and
  round-trip through `chat_messages.parts`. Phase 7 is purely rendering.
- `errorText` reaches the analyst verbatim (`describeError` has no mapping for
  stream errors), so the failure strings in `orchestrator.py` are product copy.

---

## Phase 7 — Trust UI (citations & source passages)

Goal: analysts can verify every claim in one click — this is what makes the product usable.

The shell landed with Phase 3. What's left is everything that needs real citation
data, so this phase unblocks only after Phase 6.

- [ ] Citation chips/links on assistant messages (company, filing type, date, section) — `message-bubble.tsx` currently filters to text parts, so `data-citation` parts arrive and are dropped
- [ ] Source passage panel — show underlying excerpt for selected citation
- [x] Empty states (no threads, no corpus match)
- [x] Error states (auth expired, retrieval failure, grounding failure, network/CORS) — `lib/errors.ts` maps 401/403/404/502 and network failures
- [x] Loading/streaming status during assistant run
- [ ] Verify: click a citation → see the exact passage from the filing

---

## Phase 8 — Pilot readiness

Goal: 5 senior analysts can use it for a week and report ≥3 hours saved per analyst per week.

- [x] README "Running locally" section — copy-paste commands for backend + frontend + env vars
- [ ] Seed or document how to ingest/update the corpus — `data/README.md` covers downloading only; ingestion doesn't exist yet
- [ ] Smoke-test all 10 example questions from the client brief
- [ ] Confirm chat history persists across sessions
- [ ] Confirm ~40-user scale assumptions (no hardcoded single-user shortcuts)
- [ ] Basic structured logging on backend (`structlog`) for debugging failed turns — dependency installed, not yet imported anywhere
- [ ] Review latency: streaming starts within a few seconds for typical queries

---

## Phase 9 — Deployment (Railway)

- [ ] Railway: backend service (Uvicorn, env vars, `ALLOWED_ORIGINS`)
- [ ] Railway: frontend service (Vite build, `VITE_*` env vars at build time)
- [ ] Supabase: re-enable email confirmation for production if disabled during dev
- [ ] Run `alembic upgrade head` against production Supabase (direct connection)
- [ ] Run ingestion against production database
- [ ] End-to-end test on deployed URLs with a real Driftwood-style email account

---

## Quick reference

| Doc | Purpose |
| --- | ------- |
| [client-brief.md](client-brief.md) | What Driftwood needs and example questions |
| [architecture.md](architecture.md) | System design, data model, streaming contract |
| [guides/supabase-setup.md](guides/supabase-setup.md) | Hosted Postgres + Auth |
| [guides/backend-setup.md](guides/backend-setup.md) | FastAPI + Alembic commands |
| [guides/frontend-setup.md](guides/frontend-setup.md) | Vite + React scaffold commands |