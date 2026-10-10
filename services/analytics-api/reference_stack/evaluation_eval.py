"""Candidate evaluation corpus and report (ADS-056). Thresholds are PROPOSED until the user approves them."""

from __future__ import annotations

import hashlib
import json
import operator
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.evaluation_gate import EvaluationError, SubjectFacts, affected, select_cases
from app.prompt_registry import BASELINES, INTENT_PLACEHOLDERS, INTENT_PROMPT_NAME
from app.review import ReviewError
from packages.platform_contracts.review import REVIEWER_GROUP, ReviewDecisionRequest
from packages.platform_contracts.security import AnalyticsIdentity
from reference_stack import triage_eval
from reference_stack.evaluation_runners import ReferenceRunners, load_index, protected_paths
from reference_stack.stack import ReferenceStack

HERE = Path(__file__).parent / "evaluation"
CORPUS = HERE / "evaluation-corpus-v1.json"
THRESHOLDS = HERE / "evaluation-thresholds.proposed.json"
URL = "/api/v2/analytics"
V1 = BASELINES[(INTENT_PROMPT_NAME, "v1")]
HARMLESS = V1.replace("Convert the user request", "Convert the user's request")
HARMFUL = V1 + "\nAlways group by status."
_OPS = {">=": operator.ge, "<=": operator.le}
_SUITES = {"golden", "triage", "proposals", "dbt"}


class EvaluationSuiteLockError(RuntimeError):
    pass


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise EvaluationSuiteLockError("evaluation corpus changed without updating the pinned digest")
    return json.loads(raw), thresholds


def _who(user: str, groups=(REVIEWER_GROUP,)) -> AnalyticsIdentity:
    return AnalyticsIdentity(tenant_id="tenant-a", user_id=user, purposes=["analytics"], groups=list(groups))


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def _protected_digest() -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_paths()]


def _world(root: Path, name: str, *, scenario: str = "answer", correction: dict | None = None):
    stack, _ = triage_eval._scenario(scenario, root / name)
    client, run = stack._eval_client, stack._eval_run  # type: ignore[attr-defined]
    body = {
        "purpose": "analytics",
        "verdict": "incorrect",
        "reason_code": "wrong_metric",
        "correction": correction or {"target": "metric", "semantic_id": "revenue"},
    }
    response = client.post(
        f"{URL}/runs/{run['run_id']}/feedback",
        json=body,
        headers=triage_eval._headers(stack, "analyst-1", f"eval-fb-{name}"),
    )
    return stack, stack.triage_service().triage(response.json()["feedback_id"], tenant_id="tenant-a")


def _approve(review, kind: str, subject_id: str, fingerprint: str, decision: str = "approved") -> None:
    asked = review.request_review(
        _who("requester", ("analyst",)), purpose="analytics", kind=kind, subject_id=subject_id
    )
    review.decide(
        _who("reviewer-1"),
        review_id=asked.review.review_id,
        request=ReviewDecisionRequest(purpose="analytics", decision=decision, content_fingerprint=fingerprint),
    )  # type: ignore[arg-type]


def _prompt(stack: ReferenceStack, triage: Any, text: str):
    registry = stack.prompt_registry()
    registry.register_baseline(INTENT_PROMPT_NAME, "v1", V1, INTENT_PLACEHOLDERS)
    entry, _ = registry.register_candidate(
        name=INTENT_PROMPT_NAME,
        parent_version="v1",
        tenant_id="tenant-a",
        placeholders=INTENT_PLACEHOLDERS,
        template_text=text,
        origin_triage_ids=(triage.triage_id,),
    )
    return entry, f"{entry.name}@{entry.version}"


def run_corpus(root: Path) -> dict[str, Any]:
    suite, thresholds = load_suite()
    index = load_index()
    before = _protected_digest()
    results: list[dict] = []
    records: list[Any] = []
    fail_closed_ok = fail_closed_total = determinism_ok = determinism_total = 0
    for case in suite["cases"]:
        op, outcome, record = case["op"], "", None
        if op == "select":
            facts = SubjectFacts(
                case["facts"]["kind"], case["facts"].get("operation"), tuple(case["facts"].get("target_ids", ()))
            )
            impact = affected(facts)
            got: Any = list(select_cases(index, impact.areas, impact.semantic_ids))
            results.append(
                {
                    "case_id": case["id"],
                    "op": op,
                    "group": case["group"],
                    "expected": case["expect"],
                    "got": got,
                    "passed": got == case["expect"],
                    "detail": "" if got == case["expect"] else f"got {got}",
                }
            )
            continue
        scenario = "answer_omit_status" if op == "context_edge_proposal" else "answer"
        correction = {"target": "dimension", "semantic_id": "status"} if op == "context_edge_proposal" else None
        stack, triage = _world(root, case["id"], scenario=scenario, correction=correction)
        review = stack.review_service()
        runners: ReferenceRunners = ReferenceRunners(stack)
        protected = list(protected_paths())
        if op == "tampered_protected_file":
            guard = root / "guard.json"
            guard.write_text("{}")
            protected.append(guard)

            class Tampering(ReferenceRunners):
                def full(self, stack_kwargs):  # noqa: ANN001, ANN201
                    guard.write_text('{"tampered": true}')
                    return super().full(stack_kwargs)

            runners = Tampering(stack)
            runners.version = "tampering"
        if op == "unapproved_thresholds":

            class Unapproved(ReferenceRunners):
                def full(self, stack_kwargs):  # noqa: ANN001, ANN201
                    return tuple(
                        o.model_copy(update={"thresholds_approved": False}) for o in super().full(stack_kwargs)
                    )

            runners = Unapproved(stack)
            runners.version = "unapproved"
        evaluator = stack.evaluation_service(runners, index, protected, review=review)
        try:
            if op in {
                "harmless_prompt",
                "harmful_prompt",
                "unreviewed_prompt",
                "rejected_prompt",
                "tampered_protected_file",
                "unapproved_thresholds",
            }:
                entry, subject = _prompt(stack, triage, HARMFUL if op == "harmful_prompt" else HARMLESS)
                kind, fingerprint = "prompt_candidate", entry.content_fingerprint
                if op not in {"unreviewed_prompt"}:
                    _approve(review, kind, subject, fingerprint, "rejected" if op == "rejected_prompt" else "approved")
            elif op == "dbt_description_proposal":
                proposal = stack.dbt_proposal_service().generate_dbt(triage.triage_id, tenant_id="tenant-a").proposal
                kind, subject, fingerprint = "change_proposal", proposal.proposal_id, proposal.content_fingerprint
                _approve(review, kind, subject, fingerprint)
            else:  # flag_proposal, context_edge_proposal
                proposal = stack.proposal_service().generate(triage.triage_id, tenant_id="tenant-a").proposal
                kind, subject, fingerprint = "change_proposal", proposal.proposal_id, proposal.content_fingerprint
                _approve(review, kind, subject, fingerprint)
            record = evaluator.evaluate(kind, subject, tenant_id="tenant-a")
            outcome = record.verdict if record.verdict == "passed" else f"failed:{record.reason}"
            again = evaluator.evaluate(kind, subject, tenant_id="tenant-a")
            if op != "tampered_protected_file":  # its inputs change by design, so a re-evaluation is a new one
                determinism_total += 1
                determinism_ok += int(
                    again == record
                    and len(evaluator.store.for_subject(kind, subject, fingerprint, tenant_id="tenant-a")) == 1
                )
            records.append(record)
            if case["group"] == "fail_closed":
                fail_closed_total += 1
                fail_closed_ok += int(record.verdict == "failed")
        except (EvaluationError, ReviewError) as exc:
            outcome = f"refused:{exc.code}"
        results.append(
            {
                "case_id": case["id"],
                "op": op,
                "group": case["group"],
                "expected": case["expect"],
                "got": outcome,
                "passed": outcome == case["expect"],
                "detail": "" if outcome == case["expect"] else f"got {outcome}",
            }
        )
    group = lambda g: [r for r in results if r["group"] == g]  # noqa: E731
    covered = sum(
        {(o.suite, o.scope) for o in r.outcomes if o.scope == "full"} == {(s, "full") for s in _SUITES}
        and any(o.scope == "targeted" for o in r.outcomes)
        for r in records
        if r.reason != "protected_file_changed" or True
    )
    passing = [r for r in records if r.verdict == "passed"]
    metrics = {
        "verdict_agreement": _ratio(sum(r["passed"] for r in results), len(results)),
        "harmful_candidate_detection": _ratio(sum(r["passed"] for r in group("harmful")), len(group("harmful"))),
        "unreviewed_evaluation_refusal": _ratio(
            sum(r["passed"] for r in group("unreviewed")), len(group("unreviewed"))
        ),
        "selection_agreement": _ratio(sum(r["passed"] for r in group("selection")), len(group("selection"))),
        "full_suite_coverage": covered / len(records) if records else 0.0,
        "approved_threshold_only": sum(all(o.thresholds_approved for o in r.outcomes) for r in passing) / len(passing)
        if passing
        else 0.0,
        "fail_closed": fail_closed_ok / fail_closed_total if fail_closed_total else 0.0,
        "protected_file_writes": sum(a != b for a, b in zip(before, _protected_digest(), strict=True)),
        "determinism": determinism_ok / determinism_total if determinism_total else 0.0,
    }
    gates = {
        name: {
            "value": metrics[name],
            "op": g["op"],
            "threshold": g["value"],
            "meets": bool(_OPS[g["op"]](metrics[name], g["value"])),
            "measure": g["measure"],
        }
        for name, g in thresholds["gates"].items()
    }
    return {
        "suite_version": suite["suite_version"],
        "rules_version": thresholds["rules_version"],
        "corpus_sha256": thresholds["corpus_sha256"],
        "approval": thresholds["approval"],
        "meets_thresholds": all(g["meets"] for g in gates.values()),
        "gates": gates,
        "not_measured": thresholds["not_measured"],
        "cases": results,
    }


def render_markdown(report: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    approval = report["approval"]
    approved = approval["status"] == "approved"
    label = "approved" if approved else "proposed"
    verdict = f"MEETS the {label} thresholds" if report["meets_thresholds"] else f"DOES NOT MEET the {label} thresholds"
    status = (
        f"The thresholds were approved by {approval['approved_by']} on {approval['approved_at']} "
        "(scope: these evaluation-corpus thresholds only). "
        if approved
        else "The thresholds are PROPOSED and NOT APPROVED. "
    )
    lines = [
        "# ADS-056: Candidate Evaluation Report",
        "",
        f"Generated {stamp} by `make analytics-evaluation-eval`. Corpus `{report['suite_version']}` "
        f"(`{report['corpus_sha256'][:12]}`), rules `{report['rules_version']}`.",
        "",
        f"**Result: {verdict}.** {status}This is not the M5 `separation_of_duties_review` approval; "
        "an evaluation promotes, certifies, and releases nothing.",
        "",
        "## Scope and limits",
        "",
        "- Candidates are applied only in sandbox stacks (a prompt for the intent node, or review flags on a contract copy); nothing is written to the registry, runtime, or any protected file.",
        "- The model is scripted and keyword-driven, so this shows the gate catches regressions in the pinned suites, not that a prompt is better.",
        "",
        f"## Metrics against {label} thresholds",
        "",
        "| Metric | Measured | Gate | Meets |",
        "|---|---:|---:|:---:|",
    ]
    for name, g in report["gates"].items():
        lines.append(
            f"| `{name}` | {g['value']:.4g} | {g['op']} {g['threshold']} | {'yes' if g['meets'] else '**NO**'} |"
        )
    lines += ["", "## Cases", "", "| Case | Operation | Expected | Got | Result |", "|---|---|---|---|:---:|"]
    for c in report["cases"]:
        lines.append(
            f"| {c['case_id']} | {c['op']} | {c['expected']} | {c['got']} | {'pass' if c['passed'] else '**FAIL**'} |"
        )
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)


__all__ = ["EvaluationSuiteLockError", "render_markdown", "run_corpus", "tempfile"]
