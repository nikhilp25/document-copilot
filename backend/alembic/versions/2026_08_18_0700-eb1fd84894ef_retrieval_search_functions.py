"""retrieval search functions

Revision ID: eb1fd84894ef
Revises: 75893942aef3
Create Date: 2026-08-18 07:00:15.161778

The two halves of hybrid retrieval, as SQL functions.

They exist because PostgREST — which every other query in this backend goes
through — cannot express either one. It has no way to say
`order by embedding <=> $1`, and its full-text filter matches rows without
ranking them. Both halves need a ranked `limit`, so both need real SQL.

Wrapping them as functions rather than opening a second, direct Postgres
connection keeps retrieval on the client and connection pool the app already
has. `app/retrieval/queries.py` calls these over `rpc()`.

Two functions and not one: the ranked lists are fused in Python with
Reciprocal Rank Fusion, so the database is asked only for two independent
rankings and never for a ranking policy.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eb1fd84894ef"
down_revision: str | Sequence[str] | None = "75893942aef3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Identical for both halves so fusion never has to care which arm a row came
# from. `score` means different things on each side — cosine similarity vs.
# `ts_rank_cd` — which is exactly why the fusion step reads ranks, not scores.
RESULT_COLUMNS = """
    id uuid,
    document_id uuid,
    chunk_index integer,
    content text,
    section text,
    page integer,
    metadata jsonb,
    score double precision
"""

# `security invoker` so the caller's own RLS applies. That is currently a
# formality — `document_chunks_read` grants select to every authenticated user
# — but a definer function would silently outlive that policy if it tightened.
FUNCTION_ATTRIBUTES = "language sql stable security invoker"


# `extensions.vector`, fully qualified: the initial migration installed the
# extension outside `public`, and an argument type is resolved when the
# function is created — before the function-local `search_path` below applies.
SEMANTIC_FUNCTION = f"""
create or replace function public.match_chunks_semantic(
    query_embedding extensions.vector(1536),
    match_count integer,
    filter jsonb default '{{}}'::jsonb
)
returns table ({RESULT_COLUMNS})
{FUNCTION_ATTRIBUTES}
set search_path = public, extensions
as $$
    select
        c.id,
        c.document_id,
        c.chunk_index,
        c.content,
        c.section,
        c.page,
        c.metadata,
        -- Cosine *similarity*, so higher is better on both arms.
        1 - (c.embedding <=> query_embedding)
    from public.document_chunks c
    where c.embedding is not null
      and c.metadata @> filter
    -- `<=>` and nothing else: ix_document_chunks_embedding_hnsw is built with
    -- vector_cosine_ops, and any other distance operator skips it silently and
    -- sequentially scans the corpus.
    order by c.embedding <=> query_embedding
    limit match_count;
$$
"""

# Every tsquery builder Postgres ships combines terms with AND, and an analyst
# asks whole questions. "How did NVIDIA describe demand drivers, customer
# concentration, and supply constraints?" becomes eleven ANDed lexemes, no
# chunk contains all eleven, and the lexical arm silently returns nothing —
# leaving hybrid search running on one leg for precisely the queries the
# product exists to answer.
#
# So build the query by OR. That is also what makes this a stand-in for BM25,
# which scores a bag of words rather than demanding every one of them:
# `ts_rank_cd` then ranks by how many query terms a chunk covers, how often,
# and how close together. Going through `to_tsvector` rather than string-
# munging a `websearch_to_tsquery` keeps the same stemming and stopword list
# as the indexed column, and drops the negation and phrase operators that have
# no sensible meaning inside an OR.
#
# A question of nothing but stopwords produces no lexemes, so `string_agg`
# returns NULL, `@@ NULL` matches nothing, and fusion rides on the semantic arm
# alone. That is the right degradation, and it needs no special case.
TSQUERY_FUNCTION = """
create or replace function public.analyst_tsquery(query_text text)
returns tsquery
language sql immutable
set search_path = public
as $$
    -- 'english' must match the regconfig baked into the generated
    -- search_vector column. A mismatch returns zero rows, not an error.
    select string_agg(quote_literal(lexeme), ' | ')::tsquery
    from unnest(to_tsvector('english', query_text));
$$
"""

LEXICAL_FUNCTION = f"""
create or replace function public.match_chunks_lexical(
    query_text text,
    match_count integer,
    filter jsonb default '{{}}'::jsonb
)
returns table ({RESULT_COLUMNS})
{FUNCTION_ATTRIBUTES}
set search_path = public
as $$
    select
        c.id,
        c.document_id,
        c.chunk_index,
        c.content,
        c.section,
        c.page,
        c.metadata,
        ts_rank_cd(c.search_vector, query)
    from public.document_chunks c,
         public.analyst_tsquery(query_text) query
    where c.search_vector @@ query
      and c.metadata @> filter
    -- No length normalisation: chunks are built to a 512-token target, so the
    -- length correction BM25 needs has almost nothing to correct for here.
    order by ts_rank_cd(c.search_vector, query) desc
    limit match_count;
$$
"""

SIGNATURES = (
    "public.match_chunks_semantic(extensions.vector, integer, jsonb)",
    "public.match_chunks_lexical(text, integer, jsonb)",
    "public.analyst_tsquery(text)",
)


def upgrade() -> None:
    op.execute(SEMANTIC_FUNCTION)
    op.execute(TSQUERY_FUNCTION)
    op.execute(LEXICAL_FUNCTION)

    for signature in SIGNATURES:
        # Postgres grants execute to `public` by default, but Supabase revokes
        # that on some projects. Naming the roles makes the grant independent
        # of which default is in force.
        op.execute(f"grant execute on function {signature} to authenticated")
        op.execute(f"grant execute on function {signature} to service_role")

    # PostgREST discovers callable functions from a cached schema snapshot and
    # answers 404 for anything added since. Without this, the RPCs are
    # unreachable until the API happens to restart.
    op.execute("notify pgrst, 'reload schema'")


def downgrade() -> None:
    for signature in SIGNATURES:
        op.execute(f"drop function if exists {signature}")

    op.execute("notify pgrst, 'reload schema'")
