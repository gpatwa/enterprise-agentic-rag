from app.ranking.final_rerank import (
    FinalRerankCandidate,
    FinalReranker,
    FinalRerankPolicy,
    Relaxation,
)


def candidate(
    candidate_id: str,
    *,
    score: float = 0.9,
    creator_id: str = "creator-a",
    category: str = "obby",
    freshness: float = 1.0,
    eligible: bool = True,
    safety_approved: bool = True,
    blocked: bool = False,
    original_rank: int = 1,
) -> FinalRerankCandidate:
    return FinalRerankCandidate(
        candidate_id=candidate_id,
        score=score,
        original_rank=original_rank,
        creator_id=creator_id,
        category=category,
        freshness=freshness,
        eligible=eligible,
        safety_approved=safety_approved,
        blocked=blocked,
        source="test",
        reason_codes=("source_candidate",),
    )


def test_final_list_is_deterministic_and_preserves_versions_and_evidence() -> None:
    policy = FinalRerankPolicy(policy_version="policy-v2", model_version="model-v3", limit=3)
    result = FinalReranker(policy).rerank(
        (
            candidate("exp-2", original_rank=2),
            candidate("exp-1", original_rank=1),
            candidate("exp-3", score=0.8, original_rank=3, category="simulator"),
        )
    )

    assert tuple(item.candidate_id for item in result.items) == ("exp-1", "exp-2", "exp-3")
    assert result.policy_version == "policy-v2"
    assert result.model_version == "model-v3"
    assert "eligibility_hard_filter" in result.items[0].evidence
    assert result.items[0].eligible is True


def test_hard_safety_and_blocked_rules_are_never_relaxed() -> None:
    result = FinalReranker(FinalRerankPolicy(limit=2)).rerank(
        (
            candidate("safe"),
            candidate("unsafe", safety_approved=False, original_rank=2),
            candidate("blocked", blocked=True, original_rank=3),
            candidate("ineligible", eligible=False, original_rank=4),
        )
    )
    assert tuple(item.candidate_id for item in result.items) == ("safe",)
    assert result.filtered_ineligible == 3


def test_creator_and_repetition_caps_relax_in_declared_order() -> None:
    policy = FinalRerankPolicy(limit=4, max_per_creator=1, max_per_category=1, min_categories=1)
    result = FinalReranker(policy).rerank(
        (
            candidate("a1", creator_id="a", category="one", original_rank=1),
            candidate("a2", creator_id="a", category="two", original_rank=2),
            candidate("b1", creator_id="b", category="one", original_rank=3),
            candidate("b2", creator_id="b", category="two", original_rank=4),
        )
    )

    assert tuple(item.candidate_id for item in result.items) == ("a1", "b2", "a2", "b1")
    assert result.relaxed[:2] == (Relaxation.CREATOR_CAP, Relaxation.REPETITION_CAP)


def test_freshness_and_diversity_relax_only_after_earlier_constraints() -> None:
    policy = FinalRerankPolicy(limit=2, min_freshness=0.8, min_categories=2)
    result = FinalReranker(policy).rerank(
        (
            candidate("fresh", category="one", freshness=1.0),
            candidate("stale", category="two", freshness=0.1, original_rank=2),
        )
    )

    assert tuple(item.candidate_id for item in result.items) == ("fresh", "stale")
    assert result.relaxed == (Relaxation.FRESHNESS_FLOOR,)
    assert result.items[1].relaxation is Relaxation.FRESHNESS_FLOOR


def test_empty_and_duplicate_batches_are_handled_safely() -> None:
    assert FinalReranker().rerank(()).items == ()
    try:
        FinalReranker().rerank((candidate("same"), candidate("same", original_rank=2)))
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("duplicate candidates must be rejected")
