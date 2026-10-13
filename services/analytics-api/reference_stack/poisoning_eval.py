"""Closed-loop safety and poisoning evaluation (ADS-059). Thresholds are PROPOSED until the user approves them.

Hostile feedback, candidates, proposals, approvals, and rollouts are run against the real ADS-050 to ADS-057 code on the
reference stack. After the whole campaign the evaluation checks that nothing protected changed, the golden suite still
meets its approved thresholds, production answers are unchanged, and no barred identity approved anything.
"""

from __future__ import annotations

import hashlib
import json
import operator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import inspect, text

from app.prompt_registry import INTENT_PLACEHOLDERS, INTENT_PROMPT_NAME, RegistryError
from app.review.rules import ReviewError
from packages.platform_contracts.prompt_registry import REQUIRED_CLAUSES
from packages.platform_contracts.proposals import DbtEdit, PatchOperation
from packages.platform_contracts.review import ReviewDecisionRequest
from reference_stack import golden, rollout_eval, triage_eval
from reference_stack.evaluation_runners import protected_paths
from reference_stack.stack import SERVICE_ROOT

HERE = Path(__file__).parent / "poisoning"
CORPUS = HERE / "poisoning-corpus-v1.json"
THRESHOLDS = HERE / "poisoning-thresholds.proposed.json"
URL = "/api/v2/analytics"
QUESTION = "Show monthly revenue"
_OPS = {">=": operator.ge, "<=": operator.le}
_PIPELINE_MODULES = (
    "app.rollout",
    "app.prompt_registry",
    "app.review",
    "app.proposals",
    "app.triage",
    "app.evaluation_gate",
    "app.drift",
)


class PoisoningSuiteLockError(RuntimeError):
    pass


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise PoisoningSuiteLockError("poisoning corpus changed without updating the pinned digest")
    return json.loads(raw), thresholds


def _label(status: int) -> str:
    if status in (200, 201):
        return "accepted"
    return "rejected" if 400 <= status < 500 else f"error:{status}"


def _post(stack, client, run_id: str, case: dict[str, Any], key: str | None, user: str, tenant: str | None = None):
    kwargs = {"tenant": tenant} if tenant else {}
    headers = {"Authorization": f"Bearer {stack.token(user, **kwargs)}"}
    if key:
        headers["Idempotency-Key"] = key
    return client.post(f"{URL}/runs/{run_id}/feedback", json=case["body"], headers=headers)


def _all_text(stack, *, skip: tuple[str, ...]) -> str:
    """Every stored cell outside the tables named in `skip`, for leak checks."""
    engine = stack.control.engine
    chunks = []
    with engine.connect() as connection:
        for table in inspect(engine).get_table_names():
            if table in skip or table == "alembic_version":
                continue
            chunks += [str(row) for row in connection.execute(text(f"SELECT * FROM {table}")).fetchall()]
    return "\n".join(chunks)


def _count(stack, table: str, where: str = "1=1") -> int:
    with stack.control.engine.connect() as connection:
        return connection.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {where}")).scalar()


def _triage_shape(record) -> tuple:
    return (
        record.category,
        record.rule_id,
        record.basis_kind,
        record.evidence_basis,
        record.alternates,
        record.conflict,
    )


def _run_case(case: dict, ctx: dict, root: Path, probes: dict) -> str:
    stack, client, run = ctx["stack"], ctx["client"], ctx["run"]
    op = case["op"]
    if op == "feedback":
        key = case["key"] if "key" in case else f"poison-{case['id'].lower()}-key"
        response = _post(stack, client, run["run_id"], case, key, case["user"], case.get("tenant"))
        return _label(response.status_code)
    if op == "note_injection":
        control = _post(
            stack, client, run["run_id"], {"body": {**case["body"], "note": None}}, "poison-x09-control", case["user"]
        )
        injected = _post(stack, client, run["run_id"], case, "poison-x09-note", case["user"])
        if control.status_code != 201 or injected.status_code != 201:
            return f"not_accepted:{control.status_code}/{injected.status_code}"
        service = stack.triage_service()
        same = _triage_shape(service.triage(control.json()["feedback_id"], tenant_id="tenant-a")) == _triage_shape(
            service.triage(injected.json()["feedback_id"], tenant_id="tenant-a")
        )
        stack.proposal_service().generate(
            service.triage(injected.json()["feedback_id"], tenant_id="tenant-a").triage_id, tenant_id="tenant-a"
        )
        leaked = case["marker"] in _all_text(stack, skip=("analytics_feedback",))
        ctx["inert_probe"] = (same, not leaked)
        return "inert" if same and not leaked else f"steered:same={same}:leaked={leaked}"
    if op == "feedback_flood":
        for index in range(case["count"]):
            response = _post(stack, client, run["run_id"], case, f"poison-flood-{index:03d}", case["user"])
            assert response.status_code == 201, response.text
            record = stack.triage_service().triage(response.json()["feedback_id"], tenant_id="tenant-a")
            stack.proposal_service().generate(record.triage_id, tenant_id="tenant-a")
        proposals = len(stack.proposal_service().store.list(tenant_id="tenant-a"))
        ctx["flood_proposals"] = proposals
        approved = _count(stack, "analytics_review_events", "event_type='approved'")
        return f"flood:proposals={proposals}:approved_reviews={approved}"
    if op == "prompt_clauses":
        registry = stack.prompt_registry()
        registry.register_baseline(INTENT_PROMPT_NAME, "v1", rollout_eval.V1, INTENT_PLACEHOLDERS)
        outcomes = []
        for clause in REQUIRED_CLAUSES:
            try:
                registry.register_candidate(
                    name=INTENT_PROMPT_NAME,
                    parent_version="v1",
                    tenant_id="tenant-a",
                    placeholders=INTENT_PLACEHOLDERS,
                    template_text=rollout_eval.V1.replace(clause, ""),
                )
                outcomes.append("accepted")
            except (ValidationError, RegistryError):
                outcomes.append("rejected")
        return "rejected" if set(outcomes) == {"rejected"} else "accepted"
    if op in {"patch", "dbt_edit"}:
        try:
            PatchOperation(**case["patch"]) if op == "patch" else DbtEdit(**case["edit"])
            return "accepted"
        except ValidationError:
            return "rejected"
    if op == "example":
        response = _post(stack, client, run["run_id"], case, "poison-x18-key", case["user"])
        if response.status_code != 201:
            return f"not_submitted:{response.status_code}"
        try:
            stack.example_service().from_feedback(response.json()["feedback_id"], tenant_id="tenant-a")
            return "accepted"
        except RegistryError:
            return "rejected"
    if op == "review_decide":
        world_stack, subject, clock, _ = rollout_eval._world(root, case["id"].lower(), review=False, evaluate=False)
        reviews = world_stack.review_service(now=clock)
        asked = reviews.request_review(
            rollout_eval._who("requester"), purpose="analytics", kind="prompt_candidate", subject_id=subject
        )
        name, version = subject.split("@")
        entry = world_stack.prompt_registry().get("prompt", name, version, tenant_id="tenant-a")
        try:
            reviews.decide(
                rollout_eval._who(case["decider"], tuple(case["groups"])),
                review_id=asked.review.review_id,
                request=ReviewDecisionRequest(
                    purpose="analytics", decision="approved", content_fingerprint=entry.content_fingerprint
                ),
            )
            outcome = "approved"
        except ReviewError as exc:
            outcome = f"refused:{exc.code}"
        ctx["barred_approvals"] += int(
            reviews.is_approved("prompt_candidate", subject, entry.content_fingerprint, tenant_id="tenant-a")
        )
        return outcome
    if op == "chain":
        label = rollout_eval._run_op(case["chain_op"], root / "chain", case["id"].lower(), probes)
        return label
    raise ValueError(f"unknown poisoning op {op}")


def _answer(client, stack, key: str) -> dict:
    response = client.post(
        f"{URL}/analyze",
        json={"request_text": QUESTION, "purpose": "analytics"},
        headers=triage_eval._headers(stack, "requester", key),
    )
    return response.json()


def _protected_digest() -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_paths()]


def run_corpus(root: Path) -> dict[str, Any]:
    suite, thresholds = load_suite()
    protected_before = _protected_digest()
    stack, run = triage_eval._scenario("answer", root / "attack")
    client = stack._eval_client  # type: ignore[attr-defined]
    ctx: dict[str, Any] = {"stack": stack, "client": client, "run": run, "barred_approvals": 0}
    probes: dict[str, Any] = {}
    results = []
    for case in suite["cases"]:
        got = _run_case(case, ctx, root, probes)
        results.append(
            {
                "case_id": case["id"],
                "name": case["name"],
                "group": case["group"],
                "op": case["op"],
                "expected": case["expect"],
                "got": got,
                "passed": got == case["expect"],
                "detail": "" if got == case["expect"] else f"got {got}",
            }
        )
    # Production behaviour: the same question, asked again after the campaign, gives the same answer.
    after = _answer(client, stack, "poison-after-campaign")
    same_answer = (
        after.get("state") == run.get("state") == "terminal" and after["outcome"]["result"] == run["outcome"]["result"]
    )
    golden_ok = golden.run_golden()["meets_thresholds"]
    release_mutations = 0
    for probe in probes.values():
        if not isinstance(probe, tuple):
            continue
        chain_stack, controller, _ = probe
        released = [
            v for v, _, _ in chain_stack.prompt_registry().versions("prompt", INTENT_PROMPT_NAME, status="released")
        ]
        history = controller.store.pointer_history(INTENT_PROMPT_NAME)
        release_mutations += int(released != ["v1"] or any(p.version != "v1" for p in history))
    pipeline_imports = [
        p.name
        for p in [
            *(SERVICE_ROOT / "app/runtime").glob("*.py"),
            SERVICE_ROOT / "app/main.py",
            SERVICE_ROOT / "app/api_v2.py",
        ]
        if any(f"from {m}" in p.read_text() or f"import {m}" in p.read_text() for m in _PIPELINE_MODULES)
    ]
    by_group = lambda g: [r for r in results if r["group"] == g]  # noqa: E731
    inert_same, inert_clean = ctx.get("inert_probe", (False, False))
    metrics = {
        "case_agreement": sum(r["passed"] for r in results) / len(results),
        "intake_block_rate": sum(r["passed"] for r in by_group("intake")) / len(by_group("intake")),
        "approval_block_rate": sum(r["passed"] for r in by_group("approval") + by_group("chain"))
        / len(by_group("approval") + by_group("chain")),
        "contract_block_rate": sum(r["passed"] for r in by_group("contract")) / len(by_group("contract")),
        "barred_approvals": ctx["barred_approvals"],
        "free_text_inert": float(inert_same and inert_clean),
        "flood_amplification": ctx.get("flood_proposals", 999),
        "production_answer_unchanged": float(same_answer),
        "golden_thresholds_still_met": float(golden_ok),
        "release_mutations": release_mutations,
        "pipeline_wired_into_runtime": len(pipeline_imports),
        "protected_file_writes": sum(a != b for a, b in zip(protected_before, _protected_digest(), strict=True)),
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
        "(scope: these poisoning-corpus thresholds only). "
        if approved
        else "The thresholds are PROPOSED and NOT APPROVED. "
    )
    lines = [
        "# ADS-059: Closed-Loop Safety and Poisoning Report",
        "",
        f"Generated {stamp} by `make analytics-poisoning-eval`. Corpus `{report['suite_version']}` "
        f"(`{report['corpus_sha256'][:12]}`), rules `{report['rules_version']}`.",
        "",
        f"**Result: {verdict}.** {status}This is not the M5 `separation_of_duties_review` approval, and it is not an "
        "independent review of the pipeline's code.",
        "",
        "## Scope and limits",
        "",
        "- The cases run the real ADS-050 to ADS-057 code on the reference stack with fakes only; there is no live system, no real model, and no production traffic.",
        "- Expected outcomes are hand-written from the rules. The corpus covers the attacks its author thought of; it is a regression net, not a proof of safety.",
        "- Case X23 assumes an independent reviewer approved a harmful candidate (a compromised reviewer): the control that stops it is the evaluation gate, not the review.",
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
    lines += ["", "## Cases", "", "| Case | Name | Group | Expected | Got | Result |", "|---|---|---|---|---|:---:|"]
    for c in report["cases"]:
        lines.append(
            f"| {c['case_id']} | {c['name']} | {c['group']} | {c['expected']} | {c['got']} | {'pass' if c['passed'] else '**FAIL**'} |"
        )
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)
