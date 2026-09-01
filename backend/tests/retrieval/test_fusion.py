"""Reciprocal Rank Fusion.

Pure ranking arithmetic, no I/O. The bug worth catching is a fusion that
degenerates into "whichever arm ran first wins", which would make the second
retriever decorative.
"""

from app.retrieval.fusion import RRF_K, reciprocal_rank_fusion


def test_agreement_between_arms_beats_a_single_arms_favourite() -> None:
    """The reason for running two retrievers at all."""
    semantic = ["both", "semantic-only"]
    lexical = ["lexical-only", "both"]

    ranked = [chunk_id for chunk_id, _ in reciprocal_rank_fusion([semantic, lexical])]

    assert ranked[0] == "both"


def test_results_come_back_best_first() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"]])

    assert [chunk_id for chunk_id, _ in fused] == ["a", "b", "c"]
    assert [score for _, score in fused] == sorted(
        (score for _, score in fused), reverse=True
    )


def test_a_chunk_only_one_arm_found_still_places() -> None:
    """No penalty term: full-text-only hits on rare terms must survive."""
    fused = dict(reciprocal_rank_fusion([["a"], ["b"]]))

    assert fused["b"] == 1.0 / (RRF_K + 1)


def test_scores_are_the_sum_of_reciprocal_ranks() -> None:
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["b", "a"]]))

    expected = 1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 2)
    assert fused["a"] == expected
    assert fused["b"] == expected


def test_ties_keep_the_first_rankings_order() -> None:
    """`retriever.py` passes the semantic arm first, so it breaks ties."""
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "a"]])

    assert [chunk_id for chunk_id, _ in fused] == ["a", "b"]


def test_a_smaller_k_sharpens_the_top_of_each_list() -> None:
    """`k` is the knob that stops rank 1 from dominating outright."""
    ranking = [["a", "b"]]

    sharp = dict(reciprocal_rank_fusion(ranking, k=1))
    flat = dict(reciprocal_rank_fusion(ranking, k=1000))

    assert sharp["a"] / sharp["b"] > flat["a"] / flat["b"]


def test_empty_rankings_fuse_to_nothing() -> None:
    """A stopword-only question matches no tsquery; that is not an error."""
    assert reciprocal_rank_fusion([[], []]) == []
