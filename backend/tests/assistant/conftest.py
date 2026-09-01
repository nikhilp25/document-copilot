"""A stand-in retriever and a scripted model, shared by the agent tests.

`FunctionModel` lets a test decide what the model "says" while everything else
— the tools, the output schema, the grounding validator — stays real.
"""

import uuid
from collections.abc import Callable
from datetime import date

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.retrieval.retriever import SourcePassage

QUOTE = "Excessive or shifting export controls have already reduced our ability"

CONTENT = (
    "Item 1A. Risk Factors\n"
    "Excessive or shifting export controls have already reduced our ability\n"
    "to sell Data Center compute products to customers in China."
)


def passage(chunk_index: int = 7) -> SourcePassage:
    return SourcePassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=chunk_index,
        ticker="NVDA",
        company_name="NVIDIA Corporation",
        form_type="10-K",
        fiscal_year=2025,
        filing_date=date(2025, 2, 26),
        accession_number="0001045810-25-000023",
        source_url="https://www.sec.gov/Archives/edgar/data/1045810/nvda.htm",
        section="Item 1A. Risk Factors",
        page=None,
        content=CONTENT,
        score=0.4,
    )


class FakeRetriever:
    """`DocumentRetriever`'s three methods, honouring the same signatures."""

    def __init__(self, passages: list[SourcePassage] | None = None) -> None:
        self.passages = passages if passages is not None else [passage()]
        self.searches: list[dict[str, object]] = []

    async def search(
        self,
        query: str,
        *,
        ticker: str | None = None,
        fiscal_year: int | None = None,
        form_type: str | None = None,
        top_k: int = 10,
    ) -> list[SourcePassage]:
        self.searches.append(
            {"query": query, "ticker": ticker, "fiscal_year": fiscal_year}
        )
        return self.passages

    async def read_chunk(self, chunk_id: uuid.UUID) -> SourcePassage | None:
        return next((p for p in self.passages if p.chunk_id == chunk_id), None)

    async def read_surrounding_chunks(
        self, chunk_id: uuid.UUID, *, radius: int = 1
    ) -> list[SourcePassage]:
        return self.passages


@pytest.fixture
def retriever() -> FakeRetriever:
    return FakeRetriever()


def search_call(**args: object) -> ModelResponse:
    """The model asking for a search."""
    return ModelResponse(parts=[ToolCallPart("search_filings", dict(args))])


def final(info: AgentInfo, **output: object) -> ModelResponse:
    """The output tool call PydanticAI turns into a `GroundedAnswer`."""
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])


def script(*turns: Callable[[AgentInfo], ModelResponse]) -> FunctionModel:
    """Replay one canned response per model request, holding the last."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = sum(1 for message in messages if isinstance(message, ModelResponse))
        return turns[min(step, len(turns) - 1)](info)

    return FunctionModel(respond)
