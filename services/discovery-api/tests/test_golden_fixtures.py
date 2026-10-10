from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "golden"
AGE_ORDER = {"E": 0, "E10": 1, "T": 2}
EXPERIENCE_ENUMS = {
    "genres": {"adventure", "arcade", "action", "building", "casual", "puzzle", "racing", "roleplay", "simulation", "social", "sports", "strategy"},
    "freshness_band": {"fresh", "steady", "stale"},
    "quality_band": {"high", "medium"},
    "popularity_band": {"niche", "rising", "popular"},
    "safety_state": {"approved", "restricted"},
    "availability": {"available", "unavailable"},
}
QUERY_CATEGORIES = {
    "exact-experience-id", "exact-title", "exact-phrase", "typo", "alias",
    "punctuation-sensitive", "genre-theme", "gameplay-mechanic",
    "natural-language-semantic", "multilingual-intent", "device-constrained",
    "locale-constrained", "age-constrained", "availability-constrained",
    "friend-co-play", "item-to-item", "new-user-cold-start",
    "new-item-cold-start", "freshness-quality-tradeoff", "diverse-results",
    "near-duplicate-suppression", "attractive-ineligible", "cross-tenant-near-match",
    "no-result", "social-discovery", "device-and-mechanic", "group-discovery",
}
POLICY_CATEGORIES = {
    "age", "safety", "locale", "device", "unavailable", "blocked-item",
    "creator-repetition", "cross-tenant-isolation", "consent", "cold-start",
}


def _load(name: str):
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _ids(records: list[dict], field: str) -> set[str]:
    values = [record[field] for record in records]
    assert len(values) == len(set(values))
    assert values == sorted(values)
    return set(values)


def test_golden_corpus_counts_order_enums_and_synthetic_markers():
    experiences = _load("experiences.json")
    users = _load("users.json")
    relationships = _load("relationships.json")
    queries = _load("queries.json")
    judgments = _load("judgments.json")
    policy_cases = _load("policy_cases.json")

    _ids(experiences, "experience_id")
    _ids(users, "user_id")
    _ids(relationships, "relationship_id")
    _ids(queries, "query_id")
    _ids(judgments, "judgment_id")
    _ids(policy_cases, "case_id")

    assert len(experiences) == 48
    assert len(users) == 24
    assert len(relationships) >= 16
    assert len(queries) == 30
    assert len(judgments) >= 30
    assert len(policy_cases) >= 8
    assert {item["tenant_id"] for item in experiences} == {"tenant-orbit", "tenant-lumen"}
    assert all(item["synthetic"] is True for collection in (experiences, users, relationships, queries, judgments, policy_cases) for item in collection)
    assert all(item["creator_id"].startswith("creator-") for item in experiences)
    assert all(item["age_rating"] in AGE_ORDER for item in experiences)
    for field, vocabulary in EXPERIENCE_ENUMS.items():
        values = {value for item in experiences for value in (item[field] if isinstance(item[field], list) else [item[field]])}
        assert values <= vocabulary
    assert {query["category"] for query in queries} == QUERY_CATEGORIES
    assert {case["category"] for case in policy_cases} == POLICY_CATEGORIES
    assert all(judgment["grade"] in {0, 1, 2, 3} for judgment in judgments)
    assert {query["category"] for query in queries if not query["expected_required"]} >= {"attractive-ineligible", "cross-tenant-near-match", "no-result"}


def test_golden_corpus_references_relationships_and_judgment_scope():
    experiences = _load("experiences.json")
    users = _load("users.json")
    relationships = _load("relationships.json")
    queries = _load("queries.json")
    judgments = _load("judgments.json")
    policy_cases = _load("policy_cases.json")
    experience_by_id = {item["experience_id"]: item for item in experiences}
    user_by_id = {item["user_id"]: item for item in users}
    query_by_id = {item["query_id"]: item for item in queries}

    assert len({item["creator_id"] for item in experiences}) >= 12
    for relationship in relationships:
        subject = user_by_id[relationship["subject_user_id"]]
        object_user = user_by_id[relationship["object_user_id"]]
        assert subject["tenant_id"] == object_user["tenant_id"] == relationship["tenant_id"]
        assert relationship["subject_user_id"] != relationship["object_user_id"]
    for query in queries:
        assert user_by_id[query["user_id"]]["tenant_id"] == query["tenant_id"]
        assert set(query["expected_required"]) <= set(experience_by_id)
        assert set(query["expected_forbidden"]) <= set(experience_by_id)
    for judgment in judgments:
        query = query_by_id[judgment["query_id"]]
        experience = experience_by_id[judgment["experience_id"]]
        assert experience["tenant_id"] == query["tenant_id"] or judgment["grade"] == 0
        if judgment["grade"] > 0:
            assert experience["experience_id"] in query["expected_required"]
            assert experience["availability"] == "available"
            assert experience["safety_state"] == "approved"
    for case in policy_cases:
        assert case["requested_experience_id"] in experience_by_id
        assert case["user_id"] in user_by_id


def test_required_and_forbidden_truth_is_explicit():
    queries = _load("queries.json")
    judgments = _load("judgments.json")
    positive = {(item["query_id"], item["experience_id"]) for item in judgments if item["grade"] > 0}
    negative = {(item["query_id"], item["experience_id"]) for item in judgments if item["grade"] == 0}
    for query in queries:
        for experience_id in query["expected_required"]:
            assert (query["query_id"], experience_id) in positive
        for experience_id in query["expected_forbidden"]:
            assert (query["query_id"], experience_id) in negative
    assert any(query["category"] == "new-user-cold-start" and not query["expected_required"] == [] for query in queries)
    assert any(query["category"] == "no-result" and not query["expected_required"] for query in queries)
