"""Deterministic dbt proposal rules (ADS-053, `dbt-proposal-rules-v1`).

Pure code over structured triage and validation facts. Two kinds of edit only: add a *missing* column
description (templated from the certified contract, never free text) and add a standard `unique` or
`not_null` test. A human-written description is never overwritten, and nothing here runs dbt.
"""

from __future__ import annotations

from dataclasses import dataclass

DBT_RULES_VERSION = "dbt-proposal-rules-v1"
_UNIQUE_CODES = {"fanout_suspected", "duplicate_group_keys"}
_NOT_NULL_CODES = {"invalid_metric_value"}


@dataclass(frozen=True)
class DbtFacts:
    triage_category: str
    triage_rule_id: str
    basis_kind: str
    issue_codes: tuple[str, ...] = ()
    model: str | None = None
    correction_column: str | None = None  # physical column of the corrected semantic ID
    correction_description: str | None = None  # templated from the certified contract
    key_columns: tuple[str, ...] = ()  # grain key of the metric the run used
    measure_column: str | None = None


@dataclass(frozen=True)
class DbtSpec:
    operation: str  # add_column_description | add_column_test
    model: str
    column: str
    edit: str  # description | test
    description: str | None
    test_name: str | None
    rationale_codes: tuple[str, ...]
    rule_id: str


@dataclass(frozen=True)
class NoDbtProposal:
    reason: str


def decide_dbt(facts: DbtFacts) -> DbtSpec | NoDbtProposal:
    if facts.basis_kind not in {"both", "system_evidence"}:
        return NoDbtProposal("claim_only")
    if not facts.model:
        return NoDbtProposal("no_model")
    if facts.triage_category == "execution":
        issues = set(facts.issue_codes)
        if issues & _UNIQUE_CODES:
            if len(facts.key_columns) != 1:
                return NoDbtProposal("composite_key_unsupported")
            code = sorted(issues & _UNIQUE_CODES)[0]
            return DbtSpec(
                "add_column_test",
                facts.model,
                facts.key_columns[0],
                "test",
                None,
                "unique",
                (f"triage:{facts.triage_rule_id}", f"validation:{code}"),
                "D-10",
            )
        if issues & _NOT_NULL_CODES:
            if not facts.measure_column:
                return NoDbtProposal("no_target")
            return DbtSpec(
                "add_column_test",
                facts.model,
                facts.measure_column,
                "test",
                None,
                "not_null",
                (f"triage:{facts.triage_rule_id}", "validation:invalid_metric_value"),
                "D-15",
            )
        return NoDbtProposal("no_matching_validation_code")
    if (facts.triage_category, facts.triage_rule_id) in {
        ("semantic", "T-91"),
        ("retrieval", "T-90"),
        ("retrieval", "T-80"),
    }:
        if not facts.correction_column or not facts.correction_description:
            return NoDbtProposal("no_target")
        rule = "D-20" if facts.triage_category == "semantic" else "D-30"
        return DbtSpec(
            "add_column_description",
            facts.model,
            facts.correction_column,
            "description",
            facts.correction_description,
            None,
            (f"triage:{facts.triage_rule_id}",),
            rule,
        )
    return NoDbtProposal("category_not_applicable")
