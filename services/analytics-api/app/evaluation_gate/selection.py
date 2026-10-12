"""Deterministic affected-case selection (ADS-056): what a change can touch, and the cases that follow."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubjectFacts:
    kind: str  # change_proposal | prompt_candidate | example_candidate
    operation: str | None = None  # proposal operation
    target_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Affected:
    areas: tuple[str, ...]
    semantic_ids: tuple[str, ...]
    reason: str
    sandbox: str


_RULES: dict[str, tuple[tuple[str, ...], bool, str, str]] = {
    # operation -> (areas, uses_target_ids, reason, sandbox note)
    "flag_definition_for_review": (
        ("intent", "execution"),
        True,
        "a flagged definition is read when intent is resolved and queries run",
        "review flags are added to a sandbox copy of the certified contract; nothing is written",
    ),
    "add_context_edge": (
        ("retrieval", "intent"),
        True,
        "a context edge changes what retrieval puts in the context pack",
        "not representable in the reference runtime; regression suites only",
    ),
    "review_label_collision": (
        ("ontology", "intent"),
        True,
        "a label change alters ontology resolution and clarification",
        "not representable in the reference runtime; regression suites only",
    ),
    "add_column_description": (
        ("retrieval", "intent"),
        False,
        "a column description feeds the metadata the context is built from",
        "not representable in the reference runtime; regression suites only",
    ),
    "add_column_test": (
        ("execution",),
        False,
        "a dbt test changes what data checks run before results are trusted",
        "not representable in the reference runtime; regression suites only",
    ),
}


def affected(facts: SubjectFacts) -> Affected:
    if facts.kind == "prompt_candidate":
        return Affected(
            ("intent",),
            (),
            "the prompt is the text intent extraction sends to the model",
            "the candidate prompt is rendered by the intent node in a sandbox stack",
        )
    if facts.kind == "example_candidate":
        return Affected(
            ("intent",),
            facts.target_ids,
            "an example would shape intent extraction for its IDs",
            "not representable in the reference runtime; regression suites only",
        )
    rule = _RULES.get(facts.operation or "")
    if rule is None:
        raise ValueError(f"no selection rule for operation {facts.operation!r}")
    areas, uses_ids, reason, sandbox = rule
    return Affected(areas, facts.target_ids if uses_ids else (), reason, sandbox)


def select_cases(
    index: dict[str, dict], affected_areas: tuple[str, ...], semantic_ids: tuple[str, ...]
) -> tuple[str, ...]:
    """Cases whose areas overlap the change and (when the change names IDs) whose IDs overlap too."""
    chosen = []
    for case_id, tags in sorted(index.items()):
        if not set(tags["areas"]) & set(affected_areas):
            continue
        if semantic_ids and not set(tags["semantic_ids"]) & set(semantic_ids):
            continue
        chosen.append(case_id)
    return tuple(chosen)
