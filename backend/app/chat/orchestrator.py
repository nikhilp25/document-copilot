"""One chat turn, end to end: run the agent, gate it, stream it, store it.

The order here is the product's central claim. Nothing the model wrote reaches
the analyst until its citations have been checked against the passages it
actually retrieved, so a failure is a clean refusal rather than a paragraph
that has to be taken back.

What that costs is time-to-first-token, and what pays for it are the transient
`data-status` parts: the analyst sees which filings are being searched within a
second, while the answer itself is still being written and checked.
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic_ai import Agent, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ToolCallPart

from app.assistant.agent import USAGE_LIMITS, agent
from app.assistant.deps import DocumentAgentDeps
from app.assistant.outputs import GroundedAnswer
from app.auth.dependencies import CurrentUser
from app.chat import messages as ui
from app.chat.streaming import (
    answer_stream,
    citation_part,
    error_part,
    sse,
    start_part,
    status_part,
)
from app.database import chats
from app.database import citations as citation_rows
from app.database.chats import ThreadRef
from app.database.models.chat_messages import MessageRole
from app.grounding.validator import violations
from app.retrieval.retriever import DocumentRetriever, SourcePassage

# Shown to the analyst verbatim, so they are written as product copy. Each one
# says what happened and what to do about it; none of them mention a model.
_UNGROUNDED = (
    "I could not produce an answer whose every claim traces back to a filing, "
    "so I have not shown one. Try narrowing the question to a specific company "
    "and year."
)
_TOO_MUCH_WORK = (
    "That question needed more searching than one turn allows. Try splitting "
    "it — one company or one fiscal year at a time."
)
_UNAVAILABLE = "The assistant is unavailable right now. Try again in a moment."

_READING_LABELS = {
    "read_chunk": "Re-reading a passage…",
    "read_surrounding_chunks": "Reading the surrounding filing text…",
}


async def run_turn(
    user: CurrentUser,
    thread: ThreadRef,
    *,
    question: str,
    history: Sequence[ui.UIMessage],
) -> AsyncIterator[str]:
    """Answer one question, streaming AI SDK frames and persisting the result.

    The turn owns its own message id: the `start` frame announces it before the
    row exists, and the row is written under it afterwards, so the client's
    copy and the stored one always agree.
    """
    message_id = uuid.uuid4()
    deps = DocumentAgentDeps(
        user_id=user.id, thread_id=thread.id, retriever=DocumentRetriever()
    )

    yield sse(start_part(message_id))

    answer: GroundedAnswer | None = None
    failure: str | None = None

    try:
        # `iter` rather than `run_stream_events`: the only thing worth reporting
        # mid-run is which filing is being searched, and walking the graph gets
        # that from ordinary requests. Streaming the model would buy tokens we
        # have already decided not to show until they are validated.
        async with agent.iter(
            question,
            deps=deps,
            message_history=ui.to_model_messages(history),
            usage_limits=USAGE_LIMITS,
        ) as run:
            async for node in run:
                if Agent.is_call_tools_node(node):
                    for part in node.model_response.parts:
                        if isinstance(part, ToolCallPart) and (label := _label(part)):
                            yield sse(status_part(label))

        answer = run.result.output if run.result is not None else None
    except UsageLimitExceeded:
        failure = _TOO_MUCH_WORK
    except UnexpectedModelBehavior:
        # The output validator kept rejecting the citations and the retry
        # budget ran out. Fail closed: this is the case the product exists for.
        failure = _UNGROUNDED
    except ModelHTTPError:
        failure = _UNAVAILABLE

    # The agent's own output validator already ran this check. Running it again
    # here is what makes the guarantee independent of how the agent is wired.
    if answer is not None and violations(answer, deps.retrieved):
        failure = _UNGROUNDED

    if answer is None or failure is not None:
        yield sse(error_part(failure or _UNAVAILABLE))
        yield sse({"type": "finish"})
        yield "data: [DONE]\n\n"
        return

    parts = _citation_parts(answer, deps.retrieved)

    async for frame in answer_stream(
        answer.answer, message_id=message_id, citations=parts
    ):
        yield frame

    # Only a completed, validated run is persisted, and the citations only
    # after the message they hang off exists.
    await chats.append_message(
        user,
        thread.id,
        role=MessageRole.ASSISTANT,
        content=answer.answer,
        parts=ui.assistant_parts(answer.answer, parts),
        message_id=message_id,
    )
    await citation_rows.insert_citations(
        user, message_id, _citation_rows(answer, deps.retrieved)
    )


def _label(call: ToolCallPart) -> str | None:
    """A progress line for one retrieval call, or None if it is not one.

    The call that produces the final answer arrives through this same node, and
    it is the answer being written rather than work worth narrating — so
    anything not in this map stays silent.
    """
    if call.tool_name in _READING_LABELS:
        return _READING_LABELS[call.tool_name]
    if call.tool_name != "search_filings":
        return None

    args = call.args_as_dict()
    scope = " ".join(
        str(value)
        for value in (args.get("ticker"), args.get("fiscal_year"))
        if value is not None
    )
    return f"Searching {scope or 'the filings'}…"


def _citation_parts(
    answer: GroundedAnswer, retrieved: dict[uuid.UUID, SourcePassage]
) -> list[dict[str, Any]]:
    """The wire form of each citation, camelCase for the TypeScript client."""
    return [
        citation_part(
            citation.index, _chip(retrieved[citation.chunk_id]), citation.quote
        )
        for citation in answer.citations
    ]


def _chip(passage: SourcePassage) -> dict[str, Any]:
    """Everything a citation chip and its passage panel need to render."""
    return {
        "chunkId": str(passage.chunk_id),
        "documentId": str(passage.document_id),
        "ticker": passage.ticker,
        "companyName": passage.company_name,
        "formType": passage.form_type,
        "fiscalYear": passage.fiscal_year,
        "filingDate": passage.filing_date.isoformat(),
        "accessionNumber": passage.accession_number,
        "sourceUrl": passage.source_url,
        # `page` is NULL corpus-wide — SEC HTML has no page breaks — so the
        # section is what actually locates a passage for the reader.
        "section": passage.section,
        "page": passage.page,
    }


def _citation_rows(
    answer: GroundedAnswer, retrieved: dict[uuid.UUID, SourcePassage]
) -> list[dict[str, Any]]:
    """`message_citations` rows, with the quote snapshotted as the excerpt.

    Snapshotted rather than looked up later because re-ingesting the corpus
    replaces chunk rows, and a citation that quietly changed what it said would
    break the one promise this product makes.
    """
    rows = []

    for citation in answer.citations:
        passage = retrieved[citation.chunk_id]
        rows.append(
            {
                "citation_index": citation.index,
                "chunk_id": str(passage.chunk_id),
                "document_id": str(passage.document_id),
                "excerpt": citation.quote,
                "page": passage.page,
                "section": passage.section,
            }
        )

    return rows
