"""A deterministic check that the question and the interpreted intent say the same thing (M7-H2).

A model can return a well-formed, certified intent for the wrong question (for example total revenue for "total profit"). Nothing else in
the pipeline compares the question with the intent, so this does, using only the certified ontology's own words (ids, labels, aliases):

1. every metric in the intent must be named in the question by one of its certified terms;
2. every dimension grouped by must be named (a time grouping needs a time word; a filter value in the question also names its field);
3. a grouping phrase in the question ("by X", "per X", "for each X", "across X") must name a certified dimension or a time unit, and the
   intent must group by it.

It abstains and never guesses: a mismatch ends the run as an unsupported request. It is lexical and conservative, so an unusual
phrasing of a valid question can be refused (measured as false abstention in ADS-073); it does not understand meaning.
"""

from __future__ import annotations

import re

from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.ontology import OntologySnapshot

TIME_WORDS = frozenset(
    "time date day days daily week weeks weekly month months monthly quarter quarters quarterly year years yearly annual annually hour hourly".split()
)
SKIP = frozenset("a an the each every all any order orders".split())
GROUPING = re.compile(r"(?=\b(?:by|per|across|for each|each)\s+([a-z0-9]+(?:\s+[a-z0-9]+)?))")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _stem(token: str) -> str:
    """A light plural fold: statuses -> status, categories -> category, orders -> order; status and process stay as they are."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ses", "xes", "ches", "shes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _terms(ontology: OntologySnapshot) -> dict[str, set[str]]:
    """node id -> normalised phrases that name it (its id, label, and aliases)."""
    out: dict[str, set[str]] = {}
    for node in ontology.nodes:
        if node.lifecycle != "certified":
            continue
        raw = [node.node_id.replace(".", " ").replace("_", " "), node.label]
        for key in ("aliases", "synonyms"):
            value = node.attributes.get(key)
            raw += [item for item in value if isinstance(item, str)] if isinstance(value, (list, tuple)) else []
        out.setdefault(node.node_id, set()).update(" ".join(_stem(t) for t in _tokens(r)) for r in raw if _tokens(r))
    return out


def _mentions(question_tokens: list[str], phrase: str) -> bool:
    stemmed = " ".join(_stem(t) for t in question_tokens)
    return f" {phrase} " in f" {stemmed} "


def echo_problems(question: str | None, intent: AnalyticalIntent, ontology: OntologySnapshot) -> list[str]:
    """Problem codes (empty when the question and the intent agree). Codes name concepts, not rows."""
    if not question:
        return ["no_question"]
    tokens = _tokens(question)
    terms = _terms(ontology)
    problems: list[str] = []
    for metric in intent.metrics:
        if not any(_mentions(tokens, phrase) for phrase in terms.get(metric.metric_id, {metric.metric_id})):
            problems.append(f"metric_not_in_question:{metric.metric_id}")
    filter_values = {_stem(t) for item in intent.filters for value in item.values for t in _tokens(str(value))}
    question_stems = {_stem(t) for t in tokens}
    grouped_ids = {g.dimension_id for g in intent.group_by}
    for group in intent.group_by:
        named = any(_mentions(tokens, phrase) for phrase in terms.get(group.dimension_id, {group.dimension_id}))
        if group.time_granularity:
            named = named or bool(question_stems & {_stem(w) for w in TIME_WORDS})
        named = named or bool(filter_values and filter_values & question_stems)
        if not named:
            problems.append(f"grouping_not_in_question:{group.dimension_id}")
    dimension_terms = {node_id: phrases for node_id, phrases in terms.items() if _is_dimension(node_id, ontology)}
    all_dimension_phrases = {p for phrases in dimension_terms.values() for p in phrases}
    for match in GROUPING.finditer(" ".join(tokens)):
        words = [w for w in match.group(1).split() if w not in SKIP]
        if not words:
            continue
        head = _stem(words[0])
        if head in {_stem(w) for w in TIME_WORDS}:
            if not any(g.time_granularity for g in intent.group_by):
                problems.append("question_groups_by_time_but_intent_does_not")
            continue
        phrase = next(
            (
                " ".join(_stem(w) for w in words[:n])
                for n in (2, 1)
                if " ".join(_stem(w) for w in words[:n]) in all_dimension_phrases
            ),
            None,
        )
        if phrase is None:
            problems.append(f"unrecognized_grouping:{_safe(words[0])}")
            continue
        if not any(phrase in dimension_terms.get(dimension, set()) for dimension in grouped_ids):
            problems.append(f"question_groups_by:{_safe(words[0])}_but_intent_does_not")
    return list(dict.fromkeys(problems))


def _is_dimension(node_id: str, ontology: OntologySnapshot) -> bool:
    return any(n.node_id == node_id and n.node_type == "dimension" for n in ontology.nodes)


def _safe(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word)[:40]


def explain(problems: list[str]) -> str:
    """A one-sentence, content-free reason for the caller (concept names only)."""
    return (
        "The question and the interpreted request do not match: "
        + "; ".join(p.replace("_", " ") for p in problems[:3])
        + "."
    )
