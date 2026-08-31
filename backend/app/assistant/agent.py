"""The PydanticAI agent — the only place in the backend that talks to an LLM.

Three bounded tools, a typed answer, and a validator that refuses ungrounded
output. The agent never writes SQL and never sees the database; it sees
`DocumentRetriever`, which Phase 5 built and tested on its own.

The tools are one line each on purpose. Everything they could get wrong —
ranking, filtering, neighbour windows — was settled in `app/retrieval/`, and
everything they must not get wrong is in `app/grounding/`. What is left here is
wiring, plus the docstrings, which are prompt surface: they become the tool
descriptions the model reads when deciding what to call.
"""

import uuid
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.assistant.deps import DocumentAgentDeps
from app.assistant.outputs import GroundedAnswer
from app.config import settings
from app.grounding.validator import violations
from app.retrieval.retriever import SourcePassage

INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text(encoding="utf-8")

# A cross-company question is one search per company, and the model may search
# again after reading a passage — so the ceiling has to allow a dozen or more
# tool calls without allowing an unbounded loop.
USAGE_LIMITS = UsageLimits(request_limit=25, tool_calls_limit=30)

# The output budget is what makes validator-driven self-correction possible:
# the default of 1 gives the model no attempt at all to fix a bad citation.
_RETRIES = {"tools": 2, "output": 2}


def _model() -> OpenAIResponsesModel:
    """The answering model, built from settings rather than the environment.

    Responses rather than Chat Completions: it is what the gpt-5 family's
    reasoning is built around, and what pydantic-ai's `openai:` prefix resolves
    to. Naming the class states the choice instead of inheriting it.
    """
    return OpenAIResponsesModel(
        settings.openai_chat_model,
        provider=OpenAIProvider(api_key=settings.openai_api_key),
    )


agent = Agent(
    _model(),
    deps_type=DocumentAgentDeps,
    output_type=GroundedAnswer,
    instructions=INSTRUCTIONS,
    retries=_RETRIES,
)


@agent.tool
async def search_filings(
    ctx: RunContext[DocumentAgentDeps],
    query: str,
    ticker: str | None = None,
    fiscal_year: int | None = None,
) -> list[SourcePassage]:
    """Search the filing corpus for passages relevant to a question.

    Args:
        query: What you are looking for, in plain English. Full questions work
            better than keywords — both a semantic and a full-text search run
            against it.
        ticker: Restrict to one filer, e.g. "AAPL", "MSFT", "NVDA", "AMZN",
            "GOOGL". One ticker only; search again for another company.
        fiscal_year: Restrict to one fiscal year, e.g. 2025. One year only;
            search again for another year.
    """
    return ctx.deps.remember(
        await ctx.deps.retriever.search(query, ticker=ticker, fiscal_year=fiscal_year)
    )


@agent.tool
async def read_chunk(
    ctx: RunContext[DocumentAgentDeps], chunk_id: uuid.UUID
) -> SourcePassage | None:
    """Re-read one passage in full by its chunk_id.

    Returns null if that passage is no longer in the corpus.
    """
    passage = await ctx.deps.retriever.read_chunk(chunk_id)
    if passage is None:
        return None

    return ctx.deps.remember([passage])[0]


@agent.tool
async def read_surrounding_chunks(
    ctx: RunContext[DocumentAgentDeps], chunk_id: uuid.UUID
) -> list[SourcePassage]:
    """Read a passage together with the ones either side of it in the filing.

    Use this when a retrieved passage begins or ends mid-argument and you need
    the surrounding sentences to quote it fairly.
    """
    return ctx.deps.remember(await ctx.deps.retriever.read_surrounding_chunks(chunk_id))


@agent.output_validator
def citations_are_grounded(
    ctx: RunContext[DocumentAgentDeps], answer: GroundedAnswer
) -> GroundedAnswer:
    """Refuse an answer whose citations do not hold up.

    Raising `ModelRetry` sends the specific faults back to the model as a
    correction prompt, so a fixable mistake costs one more request rather than
    the whole turn. When the retry budget runs out pydantic-ai raises, and the
    orchestrator turns that into a controlled failure — the answer never
    reaches the analyst either way.
    """
    if problems := violations(answer, ctx.deps.retrieved):
        raise ModelRetry(" ".join(problems))

    return answer
