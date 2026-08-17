"""Supabase client construction.

Two clients, two trust levels:

- `user_client(access_token)` acts *as the analyst*. PostgREST validates the
  JWT itself and runs every statement as the `authenticated` role, so the RLS
  policies from the initial migration apply. Use it for anything touching a
  user's own chat data — RLS then backstops an authorization bug in our code
  instead of leaking another analyst's threads.
- `service_client()` bypasses RLS entirely. Use it only where there is no user
  JWT (corpus ingestion) or where a write is legitimately forbidden to the
  user's own role (inserting the `users` row on first sign-in). Those call
  sites must scope rows to the authenticated `user_id` by hand.

Neither function verifies the token — `app/auth/dependencies.py` owns that, and
must reject unauthenticated requests before any client is built here.

Both clients share one HTTP connection pool. A Supabase client is a thin header
wrapper around it: PostgREST and Auth attach their per-client headers to each
request rather than mutating the shared pool, so building a client per request
is cheap and cannot leak one analyst's token into another's request.
"""

import httpx
from supabase import AsyncClient, AsyncClientOptions, create_async_client

from app.config import settings

# Server-side clients never own a session. There is no browser to persist one
# for, and a fresh token arrives on every request — leaving these on would
# start a background refresh loop for a session we never set.
_SESSION_OPTIONS = {"auto_refresh_token": False, "persist_session": False}

_http_client: httpx.AsyncClient | None = None


def _shared_http_client() -> httpx.AsyncClient:
    """The connection pool every Supabase client borrows.

    Created on first use rather than at import so nothing opens sockets while
    Alembic, pytest, or a notebook is merely importing the package.
    """
    global _http_client

    if _http_client is None:
        _http_client = httpx.AsyncClient(
            # Generous enough for ingestion's batch writes; short enough that a
            # stalled request surfaces as an error instead of a hung stream.
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            http2=True,
        )
    return _http_client


def _options(access_token: str) -> AsyncClientOptions:
    return AsyncClientOptions(
        # Set explicitly so the client skips its session lookup and uses this
        # token verbatim — the header is the only thing that decides which
        # Postgres role, and therefore which rows, the request gets.
        headers={"Authorization": f"Bearer {access_token}"},
        httpx_client=_shared_http_client(),
        **_SESSION_OPTIONS,
    )


async def user_client(access_token: str) -> AsyncClient:
    """A client scoped to one analyst, subject to RLS.

    `access_token` is the Supabase JWT from the request's `Authorization`
    header. Pair it with the anon key so PostgREST resolves the request to the
    `authenticated` role; an expired or forged token fails at PostgREST with a
    401 rather than silently reading as an anonymous user.
    """
    return await create_async_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options=_options(access_token),
    )


async def service_client() -> AsyncClient:
    """A privileged client that bypasses RLS. No user is implied by its use."""
    return await create_async_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=_options(settings.supabase_service_role_key),
    )


async def close_http_client() -> None:
    """Release the shared pool. Call once on application shutdown."""
    global _http_client

    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
