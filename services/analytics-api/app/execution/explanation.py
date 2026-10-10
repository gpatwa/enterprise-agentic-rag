"""Grounded explanation and visualization spec for a validated result (ADS-043).

The explainer is model-assisted but is only ever shown a fixed `FactSheet`: cell values
addressed by stable IDs (`cell:r0c1`) and the semantic IDs of the certified intent. A
claim is accepted only if it cites known IDs and every number in its prose appears in
the cells it cites. One repair attempt may rewrite prose; it cannot change the result,
which is verified by fingerprint before and after. If grounding still fails the answer
is returned as evidence without prose. The visualization spec is derived
deterministically from the intent shape, never from model output, and holds no data.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.execution.gateway import ExecutionResult
from app.execution.result_validation import _canonical, result_fingerprint
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import SemanticContract

MAX_FACT_ROWS = 50
MAX_CLAIMS = 8
MAX_CLAIM_CHARS = 400
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


class ExplanationIntegrityError(RuntimeError):
    """The result changed while it was being explained; nothing may be returned."""


@dataclass(frozen=True)
class Fact:
    fact_id: str
    kind: Literal["cell", "metric", "dimension", "contract"]
    value: str  # display text for cells; the semantic ID for the rest


@dataclass(frozen=True)
class FactSheet:
    result_fingerprint: str
    contract: str
    facts: tuple[Fact, ...]
    truncated_rows: bool

    def get(self, fact_id: str) -> Fact | None:
        return next((fact for fact in self.facts if fact.fact_id == fact_id), None)


@dataclass(frozen=True)
class DraftClaim:
    text: str
    cites: tuple[str, ...]


Explainer = Callable[[FactSheet, tuple[str, ...]], Sequence[DraftClaim]]
"""(fact sheet, violations from the previous attempt; empty on the first) -> draft claims."""


@dataclass(frozen=True)
class ColumnBinding:
    column_index: int
    role: Literal["dimension", "metric"]
    semantic_id: str


@dataclass(frozen=True)
class VisualizationSpec:
    kind: Literal["stat", "line", "bar", "table"]
    x: ColumnBinding | None
    y: tuple[ColumnBinding, ...]
    row_limit: int


@dataclass(frozen=True)
class Explanation:
    status: Literal["grounded", "evidence_only"]
    result_fingerprint: str
    claims: tuple[DraftClaim, ...]
    visualization: VisualizationSpec
    attempts: int
    violations: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(
                [
                    self.status,
                    self.result_fingerprint,
                    [[claim.text, list(claim.cites)] for claim in self.claims],
                    [self.visualization.kind, self.visualization.row_limit],
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


def build_fact_sheet(result: ExecutionResult, intent: AnalyticalIntent, contract: SemanticContract) -> FactSheet:
    facts: list[Fact] = [Fact(f"contract:{contract.id}@{contract.version}", "contract", contract.id)]
    facts += [Fact(f"metric:{m.metric_id}", "metric", m.metric_id) for m in intent.metrics]
    facts += [Fact(f"dimension:{g.dimension_id}", "dimension", g.dimension_id) for g in intent.group_by]
    for r, row in enumerate(result.rows[:MAX_FACT_ROWS]):
        for c, value in enumerate(row):
            facts.append(Fact(f"cell:r{r}c{c}", "cell", "" if value is None else str(_canonical(value))))
    return FactSheet(
        result_fingerprint=result_fingerprint(result),
        contract=f"{contract.id}@{contract.version}",
        facts=tuple(facts),
        truncated_rows=result.row_count > MAX_FACT_ROWS,
    )


def verify_claims(sheet: FactSheet, claims: Sequence[DraftClaim]) -> tuple[str, ...]:
    """Violation codes (never values); an empty tuple means every claim is grounded."""
    violations: list[str] = []
    if not claims:
        return ("no_claims",)
    if len(claims) > MAX_CLAIMS:
        violations.append("too_many_claims")
    for index, claim in enumerate(claims[:MAX_CLAIMS]):
        label = f"claim_{index}"
        if not claim.text.strip() or len(claim.text) > MAX_CLAIM_CHARS:
            violations.append(f"{label}:bad_text")
            continue
        facts = [sheet.get(cite) for cite in claim.cites]
        if not claim.cites or any(fact is None for fact in facts):
            violations.append(f"{label}:unknown_citation" if claim.cites else f"{label}:uncited")
            continue
        cells = [fact for fact in facts if fact and fact.kind == "cell"]
        if not cells:
            violations.append(f"{label}:no_result_cell")
            continue
        allowed = {_normalize(token) for fact in cells for token in _NUMBER.findall(fact.value)}
        if any(_normalize(token) not in allowed for token in _NUMBER.findall(claim.text)):
            violations.append(f"{label}:ungrounded_number")
    return tuple(violations)


def visualization_spec(intent: AnalyticalIntent) -> VisualizationSpec:
    metrics = tuple(
        ColumnBinding(len(intent.group_by) + i, "metric", m.metric_id) for i, m in enumerate(intent.metrics)
    )
    dims = tuple(ColumnBinding(i, "dimension", g.dimension_id) for i, g in enumerate(intent.group_by))
    if not dims:
        return VisualizationSpec("stat", None, metrics, 1)
    if len(dims) == 1:
        temporal = intent.group_by[0].time_granularity is not None
        return VisualizationSpec("line" if temporal else "bar", dims[0], metrics, min(intent.limit, MAX_FACT_ROWS))
    return VisualizationSpec("table", None, dims + metrics, min(intent.limit, MAX_FACT_ROWS))


def explain_result(
    result: ExecutionResult,
    intent: AnalyticalIntent,
    contract: SemanticContract,
    explainer: Explainer,
) -> Explanation:
    """Ground prose in the fixed result with at most one repair attempt, else evidence only."""
    before = result_fingerprint(result)
    sheet = build_fact_sheet(result, intent, contract)
    spec = visualization_spec(intent)
    violations: tuple[str, ...] = ()
    claims: tuple[DraftClaim, ...] = ()
    for attempt in (1, 2):
        try:
            claims = tuple(explainer(sheet, violations))
            violations = verify_claims(sheet, claims)
        except Exception as exc:  # noqa: BLE001 - a failing explainer degrades to evidence only.
            claims, violations = (), (f"explainer_error:{type(exc).__name__}",)
        if result_fingerprint(result) != before:
            raise ExplanationIntegrityError("result changed during explanation")
        if not violations:
            return Explanation("grounded", before, claims, spec, attempt, ())
    return Explanation("evidence_only", before, (), spec, 2, violations)


def _normalize(token: str) -> str:
    text = token.replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.lstrip("0") or "0"
