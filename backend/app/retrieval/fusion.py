"""Reciprocal Rank Fusion — how the two halves of hybrid search become one list.

The obvious move is to average the two scores, and it does not work. The
semantic arm returns cosine similarity, bounded in [0, 1] and clustered near
0.8 for anything vaguely on topic. The lexical arm returns `ts_rank_cd`, which
is unbounded and depends on term frequency. Averaging them compares quantities
that share no scale, and whichever arm happens to produce bigger numbers wins
every tie.

RRF sidesteps the problem by throwing the scores away and fusing *ranks*:

    rrf(d) = sum over each ranking r of  1 / (k + rank_r(d))

A chunk that both arms rank highly beats one that a single arm loves, which is
the whole point of running two arms. `k` flattens the curve so the top of each
list does not dominate outright; 60 is the constant from the original 2009
paper and has survived every attempt to unseat it.
"""

from collections import defaultdict

RRF_K = 60


def reciprocal_rank_fusion(
    rankings: list[list[str]], *, k: int = RRF_K
) -> list[tuple[str, float]]:
    """Fuse ranked id lists into one, best first.

    Ids missing from a ranking simply contribute nothing from that arm — there
    is no penalty term, so a chunk only one arm found still places.
    """
    scores: dict[str, float] = defaultdict(float)

    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (k + rank)

    # `sorted` is stable, so ids that tie keep the order they were first seen
    # in — the semantic arm's order, given how `retriever.py` passes them.
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
