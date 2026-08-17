"""The application-side mirror of a Supabase Auth user."""

from app.auth.dependencies import CurrentUser
from app.database.supabase import service_client


async def ensure_user_record(user: CurrentUser) -> None:
    """Create or refresh this analyst's `public.users` row.

    Supabase owns `auth.users` and nothing mirrors it into `public.users`, but
    `chat_threads.user_id` has a foreign key into the mirror — so a first-time
    analyst cannot create a thread until this row exists.

    Runs with the service client because the `users` RLS policies grant
    `select` and `update` on your own row but never `insert`. The row is keyed
    by the id from the verified JWT, so the privileged write is still pinned to
    the authenticated user. Upsert rather than insert-if-missing so a changed
    email address follows the analyst on their next thread.
    """
    client = await service_client()
    await (
        client.table("users")
        .upsert({"id": str(user.id), "email": user.email}, on_conflict="id")
        .execute()
    )
