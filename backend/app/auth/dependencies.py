"""Request authentication — the boundary every user-facing route sits behind.

`CurrentUser` is the only way route code learns who is calling. It carries the
raw access token as well as the identity, because user-scoped database work
needs the token to build a client that RLS will constrain (see
`app.database.supabase`).

Tokens are verified by asking Supabase Auth, which costs one round trip per
request but cannot be fooled by a signing mistake on our side. Local JWT
signature validation is the optimization to reach for if that round trip ever
shows up in latency numbers; it belongs behind this same function.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated
    
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import AuthError

from app.database.supabase import user_client

# `auto_error=False` so a missing or malformed header reaches our own handler.
# HTTPBearer's built-in rejection is a 403 with no detail, which is both the
# wrong status and useless to the frontend's expired-session redirect.
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The verified analyst behind the current request."""

    id: uuid.UUID
    email: str

    # The JWT this request arrived with, forwarded to `user_client()` so reads
    # and writes run as this analyst and RLS applies.
    access_token: str


def _unauthenticated(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ],
) -> CurrentUser:
    """Verify `Authorization: Bearer <supabase_jwt>` or reject with 401."""
    if credentials is None:
        raise _unauthenticated("Missing bearer token.")

    token = credentials.credentials
    client = await user_client(token)

    try:
        response = await client.auth.get_user(token)
    except AuthError as exc:
        # Expired, revoked, malformed, or issued by a different project.
        raise _unauthenticated("Invalid or expired token.") from exc

    # `get_user` only returns None when it falls back to a stored session, and
    # this client never has one — but the token is untrusted input, so treat a
    # userless response as a failed verification rather than assuming.
    if response is None or response.user is None:
        raise _unauthenticated("Invalid or expired token.")

    user = response.user
    if user.email is None:
        # Email is the only sign-in method this product enables. A user without
        # one means Supabase Auth grew a provider that nothing here handles.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authenticated user has no email address.",
        )

    return CurrentUser(id=uuid.UUID(user.id), email=user.email, access_token=token)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
