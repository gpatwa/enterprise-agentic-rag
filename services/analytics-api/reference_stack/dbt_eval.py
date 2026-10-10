"""dbt proposal corpus evaluation and report (ADS-053). Thresholds are PROPOSED until the user approves them."""

from __future__ import annotations

import hashlib
import json
import operator
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.proposals.dbt_project import DbtProject, find_column, render_edit
from reference_stack import proposal_eval, triage_eval
from reference_stack.stack import DBT_FIXTURE, ReferenceStack

HERE = Path(__file__).parent / "dbt_proposals"
CORPUS = HERE / "dbt-corpus-v1.json"
THRESHOLDS = HERE / "dbt-thresholds.proposed.json"
URL = "/api/v2/analytics"
_OPS = {">=": operator.ge, "<=": operator.le}
_SPAWNERS = (
    (subprocess, ("run", "Popen", "call", "check_call", "check_output")),
    (os, ("system", "popen", "execv", "execvp", "spawnv")),
)


class DbtSuiteLockError(RuntimeError):
    pass


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise DbtSuiteLockError("dbt corpus changed without updating the pinned digest")
    return json.loads(raw), thresholds


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + path.read_bytes())
    return digest.hexdigest()


def _protected() -> list[Path]:
    return proposal_eval._protected()


def _digests() -> list[str]:
    return proposal_eval._digests() + [_tree_digest(DBT_FIXTURE)]


def _rows(stack: ReferenceStack) -> list[int]:
    return proposal_eval._rows(stack)


class _SpawnWatch:
    """Counts process-spawn attempts for the duration of the run, then restores everything."""

    def __enter__(self) -> "_SpawnWatch":
        self.calls = 0
        self._saved = []

        def counting(*args: Any, **kwargs: Any) -> None:
            self.calls += 1
            raise PermissionError("the proposal generator must not start processes")

        for module, names in _SPAWNERS:
            for name in names:
                if hasattr(module, name):
                    self._saved.append((module, name, getattr(module, name)))
                    setattr(module, name, counting)
        return self

    def __exit__(self, *exc: object) -> None:
        for module, name, original in self._saved:
            setattr(module, name, original)


def _edit_valid(proposal: Any, root: Path) -> bool:
    """Apply the structured edit to a temporary copy; only the target column may differ afterwards."""
    copy = root / f"edit-{proposal.proposal_id[:8]}"
    shutil.copytree(DBT_FIXTURE, copy)
    edit = proposal.dbt_edit
    path = copy / edit.file_path
    before = yaml.safe_load(path.read_text())
    try:
        path.write_text(
            render_edit(
                path.read_text(), edit.model, edit.column, description=edit.description, test_name=edit.test_name
            )
        )
        after = yaml.safe_load(path.read_text())
    except Exception:  # noqa: BLE001 - an edit that does not apply or parse is invalid
        return False
    column = find_column(after, edit.model, edit.column)
    if column is None:
        return False
    if edit.edit == "description":
        applied = column.pop("description", None) == edit.description
    else:
        key = "tests" if "tests" in column else "data_tests"
        applied = edit.test_name in (column.get(key) or [])
        column.pop(key, None)
    original = find_column(before, edit.model, edit.column)
    for key in ("description", "tests", "data_tests"):
        if edit.edit == "description" and key == "description":
            original.pop(key, None)
    return applied and after == before and DbtProject(copy).locate_model(edit.model) is not None


def run_corpus(root: Path) -> dict[str, Any]:
    suite, thresholds = load_suite()
    protected_before = _digests()
    stacks: dict[str, ReferenceStack] = {}
    ids: dict[str, str] = {}
    results: list[dict] = []
    proposals = []
    counts = {"deterministic": 0, "dedupe_total": 0, "dedupe_ok": 0, "violations": 0, "commands_ok": 0, "valid": 0}
    with _SpawnWatch() as watch:
        for index, case in enumerate(suite["cases"]):
            scenario = case["scenario"]
            if scenario not in stacks:
                stacks[scenario], _ = triage_eval._scenario(scenario, root)
            stack = stacks[scenario]
            client, run = stack._eval_client, stack._eval_run  # type: ignore[attr-defined]
            headers = triage_eval._headers(stack, case["user"], f"dbt-fb-{index:04d}")
            response = client.post(
                f"{URL}/runs/{run['run_id']}/feedback",
                json={"purpose": "analytics", **case["feedback"]},
                headers=headers,
            )
            if response.status_code != 201:
                results.append({"case_id": case["id"], "passed": False, "detail": f"feedback {response.status_code}"})
                continue
            triage = stack.triage_service().triage(response.json()["feedback_id"], tenant_id="tenant-a")
            patterns = tuple(case["approved_patterns"]) if "approved_patterns" in case else None
            service = stack.dbt_proposal_service(patterns)
            result = service.generate_dbt(triage.triage_id, tenant_id="tenant-a")
            rows_after = _rows(stack)
            again = service.generate_dbt(triage.triage_id, tenant_id="tenant-a")
            counts["deterministic"] += int(
                again.proposal == result.proposal
                and not again.proposal_created
                and not again.support_added
                and _rows(stack) == rows_after
            )
            expect, proposal = case["expect"], result.proposal
            if "none" in expect:
                got = {"none": result.reason}
                passed = proposal is None and result.reason == expect["none"]
            else:
                got = (
                    {"operation": proposal.operation, "target_id": proposal.target_id}
                    if proposal
                    else {"none": result.reason}
                )
                passed = got == expect
            if proposal is not None:
                ids[case["id"]] = proposal.proposal_id
                if "duplicate_of" not in case:
                    proposals.append(proposal)
                    counts["violations"] += int(proposal.dbt_edit.file_path not in service.project.approved_files())
                    commands = proposal.validation_commands
                    counts["commands_ok"] += int(
                        commands == ("dbt parse", f"dbt test --select {proposal.dbt_edit.model}")
                    )
                    counts["valid"] += int(_edit_valid(proposal, root))
            if "duplicate_of" in case:
                counts["dedupe_total"] += 1
                counts["dedupe_ok"] += int(
                    ids.get(case["id"]) == ids.get(case["duplicate_of"])
                    and not result.proposal_created
                    and result.support_added
                )
            results.append(
                {
                    "case_id": case["id"],
                    "scenario": scenario,
                    "expected": expect,
                    "got": got,
                    "passed": bool(passed),
                    "detail": "" if passed else f"got {got}",
                }
            )
    complete = sum(
        bool(
            p.origin_triage_id
            and p.origin_feedback_id
            and p.origin_run_id
            and p.rationale_codes
            and p.rules_version
            and p.base_contract_fingerprint
        )
        for p in proposals
    )
    total = len(suite["cases"])
    metrics = {
        "proposal_agreement": sum(r["passed"] for r in results) / total,
        "provenance_completeness": complete / len(proposals) if proposals else 0.0,
        "file_constraint_violations": counts["violations"],
        "validation_command_coverage": counts["commands_ok"] / len(proposals) if proposals else 0.0,
        "commands_executed": watch.calls,
        "source_file_writes": sum(a != b for a, b in zip(protected_before, _digests(), strict=True)),
        "edit_validity": counts["valid"] / len(proposals) if proposals else 0.0,
        "determinism": counts["deterministic"] / total,
        "dedupe_agreement": counts["dedupe_ok"] / counts["dedupe_total"] if counts["dedupe_total"] else 0.0,
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
        "proposals": [p.model_dump(mode="json") for p in proposals],
    }


def render_markdown(report: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    approval = report["approval"]
    approved = approval["status"] == "approved"
    label = "approved" if approved else "proposed"
    verdict = f"MEETS the {label} thresholds" if report["meets_thresholds"] else f"DOES NOT MEET the {label} thresholds"
    status = (
        f"The thresholds were approved by {approval['approved_by']} on {approval['approved_at']} "
        "(scope: these dbt-corpus thresholds only). "
        if approved
        else "The thresholds are PROPOSED and NOT APPROVED. "
    )
    lines = [
        "# ADS-053: dbt Change Proposal Report",
        "",
        f"Generated {stamp} by `make analytics-dbt-eval`. Corpus `{report['suite_version']}` "
        f"(`{report['corpus_sha256'][:12]}`), rules `{report['rules_version']}`.",
        "",
        f"**Result: {verdict}.** {status}This is not a gate pass for any human gate and approves no proposal.",
        "",
        "## Scope and limits",
        "",
        "- Proposals are inert data (status `proposed`) against a small fixture dbt project; nothing is applied and dbt is never run.",
        "- The validation commands are text for a reviewer. Expectations were written by hand from the rule definitions on the "
        "fakes-only reference stack; they say nothing about whether the edits are good fixes.",
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
    for c in report["cases"]:
        lines.append(
            f"| {c['case_id']} | {c.get('scenario', '')} | {c.get('expected', '')} | {c.get('got', c.get('detail', ''))} | "
            f"{'pass' if c['passed'] else '**FAIL**'} |"
        )
    lines += ["", "## Proposals generated", ""]
    for p in report["proposals"]:
        lines.append(
            f"- `{p['proposal_id'][:12]}` {p['operation']} on `{p['target_id']}` in `{p['dbt_edit']['file_path']}` "
            f"(commands: {', '.join(f'`{c}`' for c in p['validation_commands'])})"
        )
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)
