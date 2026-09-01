"""What one agent run is given, and what it accumulates.

The `retrieved` ledger is the mechanism behind the product's hardest rule: the
model may cite only what it actually retrieved on this turn. Every tool routes
its results through `remember`, so by the time an answer arrives the ledger is
exactly the set of passages the model was shown — and grounding becomes a
membership test rather than a judgement call.

Per-run state, so a fresh instance is built for every turn. Two analysts asking
at once must never share one.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.retrieval.retriever import DocumentRetriever, SourcePassage


@dataclass
class DocumentAgentDeps:
    """The agent's typed dependencies for a single chat turn."""

    user_id: uuid.UUID
    thread_id: uuid.UUID
    retriever: DocumentRetriever

    # Keyed by chunk id, so a passage returned by two different searches is
    # recorded once and a citation resolves in one lookup.
    retrieved: dict[uuid.UUID, SourcePassage] = field(default_factory=dict)

    def remember(self, passages: Iterable[SourcePassage]) -> list[SourcePassage]:
        """Record what a tool is about to return, and return it unchanged.

        Written to wrap the tool's own return value so a tool cannot hand the
        model a passage without logging it — forgetting the call would be a
        silent hole in the grounding check.
        """
        seen = list(passages)

        for passage in seen:
            self.retrieved[passage.chunk_id] = passage

        return seen
