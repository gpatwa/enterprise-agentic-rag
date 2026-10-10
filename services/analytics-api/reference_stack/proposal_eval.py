"""Proposal corpus evaluation and report (ADS-052). Reports the approval status recorded with the thresholds."""

from __future__ import annotations

import hashlib
import json
import operator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.proposals.service import ProposalError
from packages.platform_contracts.proposals import ALLOWED_PATCH_PATHS, apply_patch
from packages.platform_contracts.semantic import SemanticRegistryDocument
from reference_stack import golden, triage_eval
from reference_stack.stack import ReferenceStack

HERE = Path(__file__).parent / "proposals"
CORPUS = HERE / "proposal-corpus-v1.json"
THRESHOLDS = HERE / "proposal-thresholds.json"
SERVICE_ROOT = Path(__file__).resolve().parent.parent
URL = "/api/v2/analytics"
_OPS = {">=": operator.ge, "<=": operator.le}


class ProposalSuiteLockError(RuntimeError):
    pass


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise ProposalSuiteLockError("proposal corpus changed without updating the pinned digest")
    return json.loads(raw), thresholds


def _protected() -> list[Path]:
    registry = sorted((SERVICE_ROOT / "semantic_registry/contracts").glob("*.json"))
    manifest = SERVICE_ROOT.parent.parent / "docs/execution/enterprise-analytics/agentic-data-stack-program.yaml"
    return [
        golden.CORPUS,
        golden.THRESHOLDS,
        triage_eval.CORPUS,
        triage_eval.THRESHOLDS,
        SERVICE_ROOT / "app/runtime/intent_node.py",
        manifest,
        *registry,
    ]


def _digests() -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in _protected()]


def _rows(stack: ReferenceStack) -> list[int]:
    tables = ("analytics_change_proposals", "analytics_proposal_support")
    with stack.control.engine.connect() as connection:
        return [connection.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in tables]


def run_corpus(root: Path) -> dict[str, Any]:
    suite, thresholds = load_suite()
    protected_before = _digests()
    stacks: dict[str, ReferenceStack] = {}
    ids: dict[str, str] = {}
    results: list[dict] = []
    proposals = []
    counts = {"deterministic": 0, "dedupe_total": 0, "dedupe_ok": 0, "draft_ok": 0, "draft_total": 0}
    for index, case in enumerate(suite["cases"]):
        scenario = case["scenario"]
        if scenario not in stacks:
            stacks[scenario], _ = triage_eval._scenario(scenario, root)
        stack = stacks[scenario]
        client, run = stack._eval_client, stack._eval_run  # type: ignore[attr-defined]
        headers = triage_eval._headers(stack, case["user"], f"proposal-fb-{index:04d}")
        response = client.post(
            f"{URL}/runs/{run['run_id']}/feedback", json={"purpose": "analytics", **case["feedback"]}, headers=headers
        )
        if response.status_code != 201:
            results.append({"case_id": case["id"], "passed": False, "detail": f"feedback {response.status_code}"})
            continue
        triage = stack.triage_service().triage(response.json()["feedback_id"], tenant_id="tenant-a")
        service = stack.proposal_service()
        result = service.generate(triage.triage_id, tenant_id="tenant-a")
        rows_after = _rows(stack)
        again = service.generate(triage.triage_id, tenant_id="tenant-a")
        counts["deterministic"] += int(
            again.proposal == result.proposal
            and not again.proposal_created
            and not again.support_added
            and _rows(stack) == rows_after
        )
        expect = case["expect"]
        proposal = result.proposal
        if "none" in expect:
            passed, got = proposal is None and result.reason == expect["none"], {"none": result.reason}
        else:
            got = (
                {k: getattr(proposal, k) for k in ("operation", "target_kind", "target_id")}
                if proposal
                else {"none": result.reason}
            )
            passed = got == expect
        if proposal is not None:
            ids[case["id"]] = proposal.proposal_id
            proposals.append(proposal)
            if "duplicate_of" not in case:
                document = stack.contracts.document.model_dump(mode="json")
                if proposal.draft_patch:
                    counts["draft_total"] += 1
                    patched = apply_patch(document, proposal.draft_patch)
                    try:
                        valid = SemanticRegistryDocument.model_validate(patched).lifecycle == "draft"
                    except ValueError:
                        valid = False
                    same = all(
                        patched["contract"][k] == document["contract"][k]
                        for k in ("metrics", "dimensions", "fields", "datasets", "policies", "joins")
                    )
                    counts["draft_ok"] += int(valid and same)
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
    unique = {p.proposal_id: p for p in proposals}.values()
    complete = sum(
        bool(
            p.origin_triage_id
            and p.origin_feedback_id
            and p.origin_run_id
            and p.rationale_codes
            and p.rules_version
            and p.base_contract_fingerprint
        )
        for p in unique
    )
    violations = sum(
        p.status != "proposed"
        or any(op.path not in ALLOWED_PATCH_PATHS for op in p.draft_patch)
        or any(op.path == "/lifecycle" and op.value != "draft" for op in p.draft_patch)
        for p in unique
    )
    total = len(suite["cases"])
    metrics = {
        "proposal_agreement": sum(r["passed"] for r in results) / total,
        "provenance_completeness": complete / len(unique) if unique else 0.0,
        "never_certified_violations": violations,
        "draft_validity": counts["draft_ok"] / counts["draft_total"] if counts["draft_total"] else 0.0,
        "protected_file_writes": sum(a != b for a, b in zip(protected_before, _digests(), strict=True)),
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
        "proposals": [p.model_dump(mode="json") for p in unique],
    }


def render_markdown(report: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    approval = report["approval"]
    approved = approval["status"] == "approved"
    label = "approved" if approved else "proposed"
    verdict = f"MEETS the {label} thresholds" if report["meets_thresholds"] else f"DOES NOT MEET the {label} thresholds"
    status = (
        f"The thresholds were approved by {approval['approved_by']} on {approval['approved_at']} "
        "(scope: these proposal-corpus thresholds only). "
        if approved
        else "The thresholds are PROPOSED and NOT APPROVED. "
    )
    lines = [
        "# ADS-052: Change Proposal Report",
        "",
        f"Generated {stamp} by `make analytics-proposals-eval`. Corpus `{report['suite_version']}` "
        f"(`{report['corpus_sha256'][:12]}`), rules `{report['rules_version']}`.",
        "",
        f"**Result: {verdict}.** {status}This is not a gate pass for any human gate and approves no proposal.",
        "",
        "## Scope and limits",
        "",
        "- Proposals are inert data (status `proposed`); nothing is applied, reviewed, or certified here (review is ADS-055).",
        "- Expectations were written by hand from the rule definitions on the fakes-only reference stack. They show the rules "
        "behave as specified and are safe; they say nothing about whether proposals are good fixes.",
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
            f"- `{p['proposal_id'][:12]}` {p['operation']} on {p['target_kind']} `{p['target_id']}` "
            f"(base {p['base_contract']}, status {p['status']})"
        )
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)


__all__ = ["ProposalError", "ProposalSuiteLockError", "render_markdown", "run_corpus"]
