"""Token verification at the FastAPI boundary."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from supabase import AuthApiError

from app.auth import dependencies

USER_ID = "33333333-3333-4333-8333-333333333333"


def patch_verification(monkeypatch: pytest.MonkeyPatch, result: Any) -> list[str]:
    """Stand in for Supabase Auth. Returns the tokens it was asked about.

    `result` is either the response to return or an exception to raise.
    """
    seen: list[str] = []

    async def get_user(jwt: str) -> Any:
        seen.append(jwt)
        if isinstance(result, Exception):
            raise result
        return result

    async def user_client(access_token: str) -> Any:
        return SimpleNamespace(auth=SimpleNamespace(get_user=get_user))

    monkeypatch.setattr(dependencies, "user_client", user_client)
    return seen


def verified_user(email: str | None = "analyst@driftwood.test") -> Any:
    return SimpleNamespace(user=SimpleNamespace(id=USER_ID, email=email))


def test_missing_header_is_rejected(client: TestClient) -> None:
    response = client.get("/chat/threads")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token."


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("token-without-a-scheme", id="no scheme"),
        pytest.param("Basic dXNlcjpwYXNz", id="wrong scheme"),
        pytest.param("Bearer ", id="empty credentials"),
    ],
)
def test_malformed_authorization_header_is_rejected(
    client: TestClient, header: str
) -> None:
    response = client.get("/chat/threads", headers={"Authorization": header})

    assert response.status_code == 401


def test_expired_token_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_verification(monkeypatch, AuthApiError("JWT expired", 401, "session_expired"))

    response = client.get(
        "/chat/threads", headers={"Authorization": "Bearer expired-token"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token."


def test_unrecognised_token_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Supabase answers a token it cannot place with an empty user rather than
    # an error; that is a failed verification, not an anonymous caller.
    patch_verification(monkeypatch, SimpleNamespace(user=None))

    response = client.get(
        "/chat/threads", headers={"Authorization": "Bearer unknown-token"}
    )

    assert response.status_code == 401


def test_valid_token_identifies_the_caller(
    client: TestClient, store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = patch_verification(monkeypatch, verified_user())
    store.add_thread(uuid.UUID(USER_ID), title="Apple revenue mix")

    response = client.get(
        "/chat/threads", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 200
    assert [thread["title"] for thread in response.json()] == ["Apple revenue mix"]
    # The header's token is what gets verified — and later what scopes the
    # database client, so the two must not drift apart.
    assert seen == ["valid-token"]


def test_user_without_an_email_is_a_server_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `public.users.email` is NOT NULL and email is the only enabled provider,
    # so this means Supabase Auth was reconfigured out from under us.
    patch_verification(monkeypatch, verified_user(email=None))

    response = client.get(
        "/chat/threads", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 500
