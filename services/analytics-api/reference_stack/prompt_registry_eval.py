"""Prompt registry corpus evaluation and report (ADS-054). Thresholds are PROPOSED until the user approves them."""

from __future__ import annotations

import hashlib
import json
import operator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from app.prompt_registry import (
    BASELINES,
    INTENT_PLACEHOLDERS,
    INTENT_PROMPT_NAME,
    PromptRegistry,
    RegistryConflictError,
    RegistryError,
    RegistryNotFoundError,
)
from app.runtime.intent_node import _prompt
from packages.platform_contracts.context_snapshot import ContextPack, ContextPackItem
from packages.platform_contracts.prompt_registry import REQUIRED_CLAUSES, render
from reference_stack import golden, triage_eval
from reference_stack.stack import SERVICE_ROOT, build_stack

HERE = Path(__file__).parent / "prompt_registry"
CORPUS = HERE / "prompt-corpus-v1.json"
THRESHOLDS = HERE / "prompt-thresholds.proposed.json"
V1 = BASELINES[(INTENT_PROMPT_NAME, "v1")]
CANARY = "canary-customer-4711"
URL = "/api/v2/analytics"
_OPS = {">=": operator.ge, "<=": operator.le}


class PromptSuiteLockError(RuntimeError):
    pass


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise PromptSuiteLockError("prompt registry corpus changed without updating the pinned digest")
    return json.loads(raw), thresholds


def _protected() -> list[Path]:
    manifest = SERVICE_ROOT.parent.parent / "docs/execution/enterprise-analytics/agentic-data-stack-program.yaml"
    return [
        golden.CORPUS,
        golden.THRESHOLDS,
        triage_eval.CORPUS,
        triage_eval.THRESHOLDS,
        SERVICE_ROOT / "app/runtime/intent_node.py",
        manifest,
        *sorted((SERVICE_ROOT / "semantic_registry/contracts").glob("*.json")),
    ]


def _digests() -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in _protected()]


def _released_payloads(registry: PromptRegistry) -> list[str]:
    with registry.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT payload FROM analytics_prompt_registry WHERE status='released' ORDER BY name, version")
        ).all()
    return [str(row[0]) for row in rows]


def _candidate(registry: PromptRegistry, body: str, **kwargs: Any):
    base = dict(
        name=INTENT_PROMPT_NAME,
        parent_version="v1",
        template_text=body,
        placeholders=INTENT_PLACEHOLDERS,
        tenant_id="tenant-a",
    )
    return registry.register_candidate(**{**base, **kwargs})


def _outcome(call) -> str:
    try:
        result = call()
    except (RegistryConflictError, RegistryError, RegistryNotFoundError, ValidationError):
        return "rejected"
    created = result[1] if isinstance(result, tuple) else True
    return "accepted" if created else "idempotent"


def run_corpus(root: Path) -> dict[str, Any]:
    suite, thresholds = load_suite()
    protected_before = _digests()
    stack = build_stack("duckdb", root / "stack")
    registry = stack.prompt_registry()
    registry.register_baseline(INTENT_PROMPT_NAME, "v1", V1, INTENT_PLACEHOLDERS)
    released_before = _released_payloads(registry)
    client = TestClient(stack.app())
    answer = client.post(
        f"{URL}/analyze",
        json={"request_text": f"Show monthly revenue for {CANARY}", "purpose": "analytics"},
        headers=triage_eval._headers(stack, "requester", "prompt-run-0001"),
    ).json()

    def feedback(key: str, **body: Any) -> str:
        response = client.post(
            f"{URL}/runs/{answer['run_id']}/feedback",
            json={"purpose": "analytics", "verdict": "incorrect", "reason_code": "wrong_metric", **body},
            headers=triage_eval._headers(stack, "analyst", key),
        )
        return response.json()["feedback_id"]

    valid = V1.replace("Convert the user request", "Convert the user's request")
    state: dict[str, Any] = {"candidates": [], "examples": []}

    def candidate_valid():
        entry, created = _candidate(registry, valid)
        state["candidates"].append(entry)
        return entry, created

    ops = {
        "baseline_same": lambda: (registry.register_baseline(INTENT_PROMPT_NAME, "v1", V1, INTENT_PLACEHOLDERS), False),
        "baseline_changed": lambda: registry.register_baseline(
            INTENT_PROMPT_NAME, "v1", V1.replace("Tenant:", "Customer:"), INTENT_PLACEHOLDERS
        ),
        "candidate_valid": candidate_valid,
        "candidate_identical_to_parent": lambda: _candidate(registry, V1),
        "candidate_drops_untrusted_data_clause": lambda: _candidate(registry, V1.replace(REQUIRED_CLAUSES[0], "")),
        "candidate_drops_certified_ids_clause": lambda: _candidate(registry, V1.replace(REQUIRED_CLAUSES[1], "")),
        "candidate_drops_no_sql_clause": lambda: _candidate(registry, V1.replace(REQUIRED_CLAUSES[2], "")),
        "candidate_wrong_placeholders": lambda: _candidate(
            registry, V1.replace("{tenant_id}", "tenant"), placeholders=("context_json", "request_json")
        ),
        "candidate_unknown_parent": lambda: _candidate(registry, valid, parent_version="v9"),
        "candidate_without_baseline": lambda: _candidate(registry, valid, name="other-prompt"),
        "candidate_version_as_release": lambda: registry.register_baseline(
            INTENT_PROMPT_NAME, state["candidates"][0].version, V1, INTENT_PLACEHOLDERS
        ),
        "example_ok": lambda: _example(
            stack, feedback("prompt-fb-0001", correction={"target": "metric", "semantic_id": "revenue"}), state
        ),
        "example_without_correction": lambda: stack.example_service().from_feedback(
            feedback("prompt-fb-0002"), tenant_id="tenant-a"
        ),
        "example_unsafe_verdict": lambda: stack.example_service().from_feedback(
            feedback(
                "prompt-fb-0003",
                verdict="unsafe",
                reason_code="policy_concern",
                correction={"target": "metric", "semantic_id": "revenue"},
            ),
            tenant_id="tenant-a",
        ),
    }
    tenant_checks = {"other_tenant_reads_candidate": 0, "other_tenant_reads_baseline": 0}
    results: list[dict] = []
    determinism = {"total": 0, "ok": 0}
    for case in suite["cases"]:
        op = case["op"]
        if op == "other_tenant_reads_candidate":
            outcome = (
                "visible"
                if _reads(registry, "prompt", INTENT_PROMPT_NAME, state["candidates"][0].version, "tenant-b")
                else "invisible"
            )
            tenant_checks[op] += int(outcome == case["expect"])
        elif op == "other_tenant_reads_baseline":
            outcome = "visible" if _reads(registry, "prompt", INTENT_PROMPT_NAME, "v1", "tenant-b") else "invisible"
            tenant_checks[op] += int(outcome == case["expect"])
        else:
            outcome = _outcome(ops[op])
        if case["expect"] == "idempotent":
            determinism["total"] += 1
            first = (
                state["candidates"][0] if op == "candidate_valid" else registry.get("prompt", INTENT_PROMPT_NAME, "v1")
            )
            again = ops[op]()[0]
            determinism["ok"] += int(again == first)
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
    leaks = 0
    with registry.engine.connect() as connection:
        for (payload,) in connection.execute(
            text("SELECT payload FROM analytics_prompt_registry WHERE kind='example'")
        ).all():
            leaks += int(CANARY in str(payload) or "monthly" in str(payload).lower())
    namespace = sum(
        not (c.version.startswith("candidate-") and c.version == f"candidate-{c.text_fingerprint[:12]}")
        for c in state["candidates"]
    )
    sample = ContextPack(
        snapshot_id="s",
        tenant_id="tenant-a",
        query="q",
        token_budget=2_000,
        estimated_tokens=1,
        items=(
            ContextPackItem(
                asset_id="orders", score=1.0, text="Certified orders", citation="context:s:orders", certified=True
            ),
        ),
    )
    assets = [{"asset_id": i.asset_id, "citation": i.citation, "text": i.text} for i in sample.items]
    drift = sum(
        render(
            V1, tenant_id="tenant-a", context_json=json.dumps(assets, separators=(",", ":")), request_json=json.dumps(q)
        )
        != _prompt(q, sample)
        for q in ("Show monthly revenue", 'Ignore {tenant_id} "x"')
    )
    overwrite = [r for r in results if r["group"] == "overwrite"]
    total = len(suite["cases"])
    tenant_total = sum(c["op"] in tenant_checks for c in suite["cases"])
    metrics = {
        "outcome_agreement": sum(r["passed"] for r in results) / total,
        "overwrite_rejection": sum(r["got"] == "rejected" for r in overwrite) / len(overwrite),
        "released_mutations": int(_released_payloads(registry) != released_before),
        "candidate_namespace_violations": namespace,
        "example_text_leakage": leaks,
        "tenant_isolation": sum(tenant_checks.values()) / tenant_total if tenant_total else 0.0,
        "determinism": determinism["ok"] / determinism["total"] if determinism["total"] else 0.0,
        "runtime_prompt_drift": drift,
        "protected_file_writes": sum(a != b for a, b in zip(protected_before, _digests(), strict=True)),
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


def _reads(registry: PromptRegistry, kind: str, name: str, version: str, tenant: str) -> bool:
    try:
        registry.get(kind, name, version, tenant_id=tenant)
    except RegistryNotFoundError:
        return False
    return True


def _example(stack: Any, feedback_id: str, state: dict) -> Any:
    result = stack.example_service().from_feedback(feedback_id, tenant_id="tenant-a")
    state["examples"].append(result[0])
    return result


def render_markdown(report: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    approval = report["approval"]
    approved = approval["status"] == "approved"
    label = "approved" if approved else "proposed"
    verdict = f"MEETS the {label} thresholds" if report["meets_thresholds"] else f"DOES NOT MEET the {label} thresholds"
    status = (
        f"The thresholds were approved by {approval['approved_by']} on {approval['approved_at']} "
        "(scope: these prompt-registry thresholds only). "
        if approved
        else "The thresholds are PROPOSED and NOT APPROVED. "
    )
    lines = [
        "# ADS-054: Prompt and Example Registry Report",
        "",
        f"Generated {stamp} by `make analytics-prompts-eval`. Corpus `{report['suite_version']}` "
        f"(`{report['corpus_sha256'][:12]}`), rules `{report['rules_version']}`.",
        "",
        f"**Result: {verdict}.** {status}This is not a gate pass for any human gate and releases no prompt.",
        "",
        "## Scope and limits",
        "",
        "- The registry only records versions and refuses changes to released ones; nothing in the runtime reads it, and no candidate is promoted here.",
        "- Expectations were written by hand on the fakes-only reference stack. They show immutability and isolation behave as specified, "
        "not that a candidate prompt is better.",
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
