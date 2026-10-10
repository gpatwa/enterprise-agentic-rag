"""Triage corpus evaluation and report (ADS-051). Thresholds are PROPOSED until the user approves."""

from __future__ import annotations

import hashlib
import json
import operator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reference_stack.stack import ReferenceStack, build_stack

HERE = Path(__file__).parent / "triage"
CORPUS = HERE / "triage-corpus-v1.json"
THRESHOLDS = HERE / "triage-thresholds.proposed.json"
URL = "/api/v2/analytics"
_OPS = {">=": operator.ge, "<=": operator.le}
_CLARIFY_ROUNDS = 3


class TriageSuiteLockError(RuntimeError):
    pass


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise TriageSuiteLockError("triage corpus changed without updating the pinned digest")
    return json.loads(raw), thresholds


def _headers(stack: ReferenceStack, user: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {stack.token(user)}"}
    return {**headers, "Idempotency-Key": key} if key else headers


def _analyze(stack, client, question: str) -> dict:
    response = client.post(
        f"{URL}/analyze",
        json={"request_text": question, "purpose": "analytics"},
        headers=_headers(stack, "requester", "triage-run-0001"),
    )
    return response.json()


def _scenario(name: str, root: Path) -> tuple[ReferenceStack, dict]:
    options: dict[str, Any] = {
        "answer": {},
        "answer_omit_status": {"omit_context_ids": ("status",)},
        "policy_denied": {"denied": True},
        "unsupported_question": {},
        "clarification_exhausted": {"ambiguous": True},
        "cost_budget": {"max_cost_units": 1e-6},
    }[name]
    stack = build_stack("duckdb", root / name, **options)
    client = TestClient(stack.app())
    question = "Tell me a joke" if name == "unsupported_question" else "Show monthly revenue"
    run = _analyze(stack, client, question)
    if name == "clarification_exhausted":
        for _ in range(_CLARIFY_ROUNDS):
            if run["state"] == "terminal":
                break
            ask = run["outcome"]["questions"][0]
            run = client.post(
                f"{URL}/runs/{run['run_id']}/clarify",
                json={"purpose": "analytics", "ambiguity_code": ask["id"], "selected_id": ask["choices"][0]["id"]},
                headers=_headers(stack, "requester"),
            ).json()
    stack._eval_client, stack._eval_run = client, run  # type: ignore[attr-defined]
    return stack, run


def run_corpus(root: Path) -> dict[str, Any]:
    suite, thresholds = load_suite()
    stacks: dict[str, ReferenceStack] = {}
    results = []
    counters = {"claim_only_failed": 0, "mutations": 0}
    decisions: dict[str, dict] = {}
    for index, case in enumerate(suite["cases"]):
        if case["scenario"] not in stacks:
            stacks[case["scenario"]], _ = _scenario(case["scenario"], root)
        stack = stacks[case["scenario"]]
        client, run = stack._eval_client, stack._eval_run  # type: ignore[attr-defined]
        feedback = {"purpose": "analytics", **case["feedback"]}
        response = client.post(
            f"{URL}/runs/{run['run_id']}/feedback",
            json=feedback,
            headers=_headers(stack, "analyst", f"triage-fb-{index:04d}"),
        )
        if response.status_code != 201:
            results.append(
                {
                    "case_id": case["id"],
                    "passed": False,
                    "detail": f"feedback {response.status_code} {response.text[:80]}",
                }
            )
            continue
        service = stack.triage_service()
        record = service.triage(response.json()["feedback_id"], tenant_id="tenant-a")
        again = service.triage(response.json()["feedback_id"], tenant_id="tenant-a")
        expect = case["expect"]
        got = {
            "category": record.category,
            "rule_id": record.rule_id,
            "basis_kind": record.basis_kind,
            "conflict": record.conflict,
        }
        counters["mutations"] += int(again != record)
        counters["claim_only_failed"] += int(
            record.basis_kind == "reporter_claim"
            and stack.evidence.get(run["run_id"], tenant_id="tenant-a", purpose="analytics").terminal_kind
            != "succeeded"
        )
        decisions[case["id"]] = {
            **got,
            "alternates": list(record.alternates),
            "fingerprint": record.decision_fingerprint,
            "again": again.decision_fingerprint,
        }
        results.append(
            {
                "case_id": case["id"],
                "scenario": case["scenario"],
                "expected": expect,
                "got": got,
                "category_ok": got["category"] == expect["category"],
                "passed": got == expect,
                "detail": "" if got == expect else f"got {got}",
            }
        )
    twins = [c for c in suite["cases"] if "twin_of" in c]
    # A twin differs from its original only in an injected note; compare decision content, not fingerprints.
    twin_ok = sum(
        1
        for c in twins
        if c["id"] in decisions
        and c["twin_of"] in decisions
        and _content(decisions[c["id"]]) == _content(decisions[c["twin_of"]])
    )
    undetermined = [d for d in decisions.values() if d["category"] == "undetermined"]
    total = len(suite["cases"])
    metrics = {
        "category_agreement": sum(r.get("category_ok", False) for r in results) / total,
        "rule_agreement": sum(r["passed"] for r in results) / total,
        "determinism": sum(d["fingerprint"] == d["again"] for d in decisions.values()) / total,
        "undetermined_lists_candidates": (sum(bool(d["alternates"]) for d in undetermined) / len(undetermined))
        if undetermined
        else 1.0,
        "note_independence": twin_ok / len(twins) if twins else 1.0,
        "claim_only_over_failed_runs": counters["claim_only_failed"],
        "record_mutations": counters["mutations"],
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
        f"The thresholds were approved by {approval['approved_by']} on {approval['approved_at']}. "
        if approved
        else "The thresholds are PROPOSED and NOT APPROVED. "
    )
    lines = [
        "# ADS-051: Triage Corpus Report",
        "",
        f"Generated {stamp} by `make analytics-triage-eval`. Corpus `{report['suite_version']}` "
        f"(`{report['corpus_sha256'][:12]}`), rules `{report['rules_version']}`.",
        "",
        f"**Result: {verdict}.** {status}This is not a gate pass for any human gate.",
        "",
        "## Scope and limits",
        "",
        "- Deterministic rules checked against labels written by hand from the rule definitions, on runs from the fakes-only reference stack.",
        "- It shows the rules behave as specified and that notes cannot steer them. It says nothing about triage quality on real feedback.",
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
    lines += ["", "## Cases", "", "| Case | Scenario | Expected | Got | Result |", "|---|---|---|---|:---:|"]
    for case in report["cases"]:
        exp = case.get("expected", {})
        got = case.get("got", {})
        lines.append(
            f"| {case['case_id']} | {case.get('scenario', '')} | {_fmt(exp, case)} | {_fmt(got, case)} | "
            f"{'pass' if case['passed'] else '**FAIL**'} |"
        )
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)


def _content(decision: dict) -> dict:
    return {k: v for k, v in decision.items() if k not in {"fingerprint", "again"}}


def _fmt(decision: dict, case: dict) -> str:
    if not decision:
        return case.get("detail", "")
    return (
        f"{decision['category']} / {decision['rule_id']} / {decision['basis_kind']} / conflict={decision['conflict']}"
    )
