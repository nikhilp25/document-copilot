"""Chat routes: the analyst's threads, and the streaming turn endpoint.

Authorization is the same three lines everywhere — find the thread, 404 if it
doesn't exist, 403 if it isn't yours — so it lives in `_authorize` and every
route goes through it. The thread id arrives in the path for CRUD and in the
body for `/chat/stream`, which is why it isn't purely a FastAPI dependency.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.wire import WireModel
from app.auth.dependencies import CurrentUser, CurrentUserDep
from app.chat import messages as ui
from app.chat import orchestrator
from app.chat.streaming import STREAM_HEADERS
from app.database import chats
from app.database.models.chat_messages import MessageRole
from app.database.users import ensure_user_record

router = APIRouter(prefix="/chat", tags=["chat"])


class ThreadResponse(WireModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageResponse(WireModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    parts: list[dict[str, Any]] | None
    created_at: datetime


class ThreadDetailResponse(WireModel):
    """A thread and its history — one round trip for a deep link into a chat."""

    thread: ThreadResponse
    messages: list[MessageResponse]


class CreateThreadRequest(WireModel):
    title: str | None = None


class StreamRequest(WireModel):
    thread_id: uuid.UUID
    messages: list[ui.UIMessage]


async def _authorize(user: CurrentUser, thread_id: uuid.UUID) -> chats.ThreadRef:
    """Resolve a thread the caller is allowed to touch, or refuse."""
    thread = await chats.find_thread(thread_id)

    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found."
        )
    if thread.user_id != user.id:
        # Deliberately distinguishable from 404, per the architecture doc's
        # error table. It admits the thread exists, which over unguessable
        # UUIDs tells an attacker nothing they could act on.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This thread belongs to another user.",
        )
    return thread


async def _authorized_thread(
    thread_id: uuid.UUID, user: CurrentUserDep
) -> chats.ThreadRef:
    return await _authorize(user, thread_id)


AuthorizedThread = Annotated[chats.ThreadRef, Depends(_authorized_thread)]


@router.get("/threads", response_model=list[ThreadResponse])
async def list_threads(user: CurrentUserDep) -> list[dict[str, Any]]:
    """This analyst's threads, most recently active first."""
    return await chats.list_threads(user)


@router.post(
    "/threads", response_model=ThreadResponse, status_code=status.HTTP_201_CREATED
)
async def create_thread(
    user: CurrentUserDep, body: CreateThreadRequest | None = None
) -> dict[str, Any]:
    """Open a thread. Untitled until the first turn names it."""
    # `chat_threads.user_id` points at `public.users`, which Supabase does not
    # populate from `auth.users` — without this the first thread hits an FK
    # violation on an otherwise perfectly authenticated request.
    await ensure_user_record(user)

    return await chats.create_thread(user, title=body.title if body else None)


@router.get("/threads/{thread_id}", response_model=ThreadDetailResponse)
async def get_thread(user: CurrentUserDep, thread: AuthorizedThread) -> dict[str, Any]:
    """A thread with its full message history."""
    return {
        "thread": await chats.get_thread(user, thread.id),
        "messages": await chats.load_messages(user, thread.id),
    }


@router.post("/stream")
async def stream_turn(user: CurrentUserDep, body: StreamRequest) -> StreamingResponse:
    """Run one chat turn and stream the reply in the AI SDK's wire format."""
    thread = await _authorize(user, body.thread_id)
    question, question_text = _latest_question(body.messages)

    # Written before the stream opens, not after it closes: if the connection
    # drops mid-answer the analyst's question still survives, and the thread
    # they reload matches the one they were looking at.
    await chats.append_message(
        user,
        thread.id,
        role=MessageRole.USER,
        content=question_text,
        parts=question.parts,
    )
    if thread.title is None:
        await chats.set_thread_title(user, thread.id, ui.derive_title(question_text))

    # Everything after this point — running the agent, gating it on grounding,
    # streaming it, storing it — belongs to the orchestrator. The route's job
    # was authorization and getting the question out of the wire format.
    stream = orchestrator.run_turn(
        user,
        thread,
        question=question_text,
        history=body.messages[:-1],
    )

    return StreamingResponse(
        stream, media_type="text/event-stream", headers=STREAM_HEADERS
    )


def _latest_question(messages: list[ui.UIMessage]) -> tuple[ui.UIMessage, str]:
    """The user message this turn answers."""
    if not messages or messages[-1].role != "user":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The last message must be from the user.",
        )

    message = messages[-1]
    text = ui.text_of(message)
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The user message has no text content.",
        )
    return message, text
