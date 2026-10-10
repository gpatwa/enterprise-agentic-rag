"""Review workflow corpus evaluation and report (ADS-055). Thresholds are PROPOSED until the user approves them."""

from __future__ import annotations

import hashlib
import json
import operator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.prompt_registry import BASELINES, INTENT_PLACEHOLDERS, INTENT_PROMPT_NAME
from app.review import ReviewError, ReviewService
from packages.platform_contracts.review import REVIEWER_GROUP, ReviewDecisionRequest
from packages.platform_contracts.security import AnalyticsIdentity
from reference_stack import golden, triage_eval
from reference_stack.stack import SERVICE_ROOT, ReferenceStack

HERE = Path(__file__).parent / "review"
CORPUS = HERE / "review-corpus-v1.json"
THRESHOLDS = HERE / "review-thresholds.proposed.json"
URL = "/api/v2/analytics"
T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
V1 = BASELINES[(INTENT_PROMPT_NAME, "v1")]
_OPS = {">=": operator.ge, "<=": operator.le}
_FORBIDDEN = {
    "generator_decides",
    "model_decides",
    "feedback_submitter_decides",
    "requester_decides",
    "non_reviewer_decides",
    "other_tenant_decides",
    "purpose_not_authorized",
    "double_decision",
    "prompt_candidate_creator",
    "example_submitter_decides",
}
_STALE = {"wrong_fingerprint", "subject_changed"}


class ReviewSuiteLockError(RuntimeError):
    pass


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise ReviewSuiteLockError("review corpus changed without updating the pinned digest")
    return json.loads(raw), thresholds


def _who(user: str, *, groups=(REVIEWER_GROUP,), tenant="tenant-a", purposes=("analytics",)) -> AnalyticsIdentity:
    return AnalyticsIdentity(tenant_id=tenant, user_id=user, purposes=list(purposes), groups=list(groups))


def _decision(fingerprint: str, decision: str = "approved", purpose: str = "analytics") -> ReviewDecisionRequest:
    return ReviewDecisionRequest(purpose=purpose, decision=decision, content_fingerprint=fingerprint)  # type: ignore[arg-type]


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@dataclass
class World:
    stack: ReferenceStack
    clock: _Clock
    service: ReviewService
    proposal: Any
    triage: Any
    reviews: list = field(default_factory=list)  # (review_id, kind, subject_id, fingerprint)


def _world(root: Path, name: str) -> World:
    stack, _ = triage_eval._scenario("answer", root / name)
    client, run = stack._eval_client, stack._eval_run  # type: ignore[attr-defined]
    response = client.post(
        f"{URL}/runs/{run['run_id']}/feedback",
        json={
            "purpose": "analytics",
            "verdict": "incorrect",
            "reason_code": "wrong_metric",
            "correction": {"target": "metric", "semantic_id": "revenue"},
        },
        headers=triage_eval._headers(stack, "analyst-1", "review-fb-0001"),
    )
    triage = stack.triage_service().triage(response.json()["feedback_id"], tenant_id="tenant-a")
    proposal = stack.proposal_service().generate(triage.triage_id, tenant_id="tenant-a").proposal
    clock = _Clock()
    return World(stack, clock, stack.review_service(now=clock), proposal, triage)


def _request(world: World, kind="change_proposal", subject_id=None, required=1):
    subject = subject_id or world.proposal.proposal_id
    status = world.service.request_review(
        _who("requester", groups=("analyst",)),
        purpose="analytics",
        kind=kind,
        subject_id=subject,
        required_approvals=required,
    )
    world.reviews.append((status.review.review_id, kind, subject, status.review.subject.content_fingerprint))
    return status


def _prompt_candidate(world: World):
    registry = world.stack.prompt_registry()
    registry.register_baseline(INTENT_PROMPT_NAME, "v1", V1, INTENT_PLACEHOLDERS)
    entry, _ = registry.register_candidate(
        name=INTENT_PROMPT_NAME,
        parent_version="v1",
        tenant_id="tenant-a",
        placeholders=INTENT_PLACEHOLDERS,
        template_text=V1.replace("Convert the user request", "Convert the user's request"),
        origin_triage_ids=(world.triage.triage_id,),
    )
    return entry


def _decide(world: World, identity: AnalyticsIdentity, review_id: str, request: ReviewDecisionRequest) -> str:
    try:
        return world.service.decide(identity, review_id=review_id, request=request).state
    except ReviewError as exc:
        return f"refused:{exc.code}"


def _asked(world: World, **kwargs: Any) -> str:
    try:
        return _request(world, **kwargs).review.review_id
    except ReviewError as exc:
        return f"refused:{exc.code}"


def _fp(world: World) -> str:
    return world.proposal.content_fingerprint


def _simple(identity: AnalyticsIdentity, *, fingerprint: str | None = None, purpose: str = "analytics"):
    def run(world: World) -> str:
        return _decide(world, identity, _asked(world), _decision(fingerprint or _fp(world), purpose=purpose))

    return run


def _subject_changed(world: World) -> str:
    review_id = _asked(world)
    real = world.service.resolver.resolve
    world.service.resolver.resolve = lambda *a, **k: real(*a, **k).model_copy(update={"content_fingerprint": "1" * 64})  # type: ignore[method-assign]
    try:
        return _decide(world, _who("reviewer-1"), review_id, _decision(_fp(world)))
    finally:
        world.service.resolver.resolve = real  # type: ignore[method-assign]


def _double_decision(world: World) -> str:
    review_id = _asked(world, required=2)
    _decide(world, _who("reviewer-1"), review_id, _decision(_fp(world)))
    return _decide(world, _who("reviewer-1"), review_id, _decision(_fp(world)))


def _reject_then_approve(world: World) -> str:
    review_id = _asked(world)
    _decide(world, _who("reviewer-1"), review_id, _decision(_fp(world), "rejected"))
    return _decide(world, _who("reviewer-2"), review_id, _decision(_fp(world)))


def _two_approvals(world: World) -> str:
    review_id = _asked(world, required=2)
    _decide(world, _who("reviewer-1"), review_id, _decision(_fp(world)))
    return _decide(world, _who("reviewer-2"), review_id, _decision(_fp(world)))


def _after_expiry(world: World) -> str:
    review_id = _asked(world)
    world.clock.now += timedelta(hours=73)
    return _decide(world, _who("reviewer-1"), review_id, _decision(_fp(world)))


def _prompt_op(identity: AnalyticsIdentity):
    def run(world: World) -> str:
        entry = _prompt_candidate(world)
        review_id = _asked(world, kind="prompt_candidate", subject_id=f"{entry.name}@{entry.version}")
        return _decide(world, identity, review_id, _decision(entry.content_fingerprint))

    return run


def _example_submitter(world: World) -> str:
    example, _ = world.stack.example_service().from_feedback(world.triage.feedback_id, tenant_id="tenant-a")
    review_id = _asked(world, kind="example_candidate", subject_id=f"{example.name}@{example.version}")
    return _decide(world, _who("analyst-1"), review_id, _decision(example.content_fingerprint))


def _released_baseline(world: World) -> str:
    _prompt_candidate(world)
    return _asked(world, kind="prompt_candidate", subject_id=f"{INTENT_PROMPT_NAME}@v1")


def _pending(world: World) -> str:
    review_id = _asked(world)
    approved = world.service.is_approved(
        "change_proposal", world.proposal.proposal_id, _fp(world), tenant_id="tenant-a"
    )
    return "approved" if approved else world.service.status(review_id, tenant_id="tenant-a").state


OPS = {
    "approve_independent": lambda w: _decide(w, _who("reviewer-1"), _asked(w), _decision(_fp(w))),
    "generator_decides": _simple(_who("system:proposal-generator")),
    "model_decides": _simple(_who("model:gpt-x")),
    "feedback_submitter_decides": _simple(_who("analyst-1")),
    "requester_decides": _simple(_who("requester")),
    "non_reviewer_decides": _simple(_who("reviewer-1", groups=("analyst",))),
    "other_tenant_decides": _simple(_who("reviewer-1", tenant="tenant-b")),
    "purpose_not_authorized": _simple(_who("reviewer-1"), purpose="billing"),
    "wrong_fingerprint": _simple(_who("reviewer-1"), fingerprint="0" * 64),
    "subject_changed": _subject_changed,
    "decide_after_expiry": _after_expiry,
    "reject_then_approve": _reject_then_approve,
    "double_decision": _double_decision,
    "two_approvals_required": _two_approvals,
    "prompt_candidate_independent": _prompt_op(_who("reviewer-1")),
    "prompt_candidate_creator": _prompt_op(_who("system:candidate")),
    "example_submitter_decides": _example_submitter,
    "released_baseline": _released_baseline,
    "pending_is_not_approved": _pending,
    "unknown_subject": lambda w: _asked(w, kind="change_proposal", subject_id="no-such-proposal"),
}


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


def run_corpus(root: Path) -> dict[str, Any]:
    suite, thresholds = load_suite()
    protected_before = _digests()
    results: list[dict] = []
    worlds: list[World] = []
    for case in suite["cases"]:
        world = _world(root, case["id"])
        worlds.append(world)
        outcome = OPS[case["op"]](world)
        results.append(
            {
                "case_id": case["id"],
                "op": case["op"],
                "group": case["group"],
                "expected": case["expect"],
                "got": outcome,
                "passed": outcome == case["expect"],
                "detail": "" if outcome == case["expect"] else f"got {outcome}",
            }
        )
    by_op = {c["id"]: c["op"] for c in suite["cases"]}
    forbidden = [r for r in results if r["op"] in _FORBIDDEN]
    stale = [r for r in results if r["op"] in _STALE]
    expiry = [r for r in results if r["op"] == "decide_after_expiry"]
    audited = determ = reviews = unsafe = mutations = expiry_ok = 0
    for case, world in zip(suite["cases"], worlds, strict=True):
        if world.stack.proposal_service().store.get(world.proposal.proposal_id, tenant_id="tenant-a") != world.proposal:
            mutations += 1
        for review_id, kind, subject_id, fingerprint in world.reviews:
            reviews += 1
            status = world.service.status(review_id, tenant_id="tenant-a")
            events = status.events
            audited += int(
                bool(events)
                and [e.seq for e in events] == list(range(1, len(events) + 1))
                and events[0].event_type == "requested"
                and all(e.actor and e.created_at for e in events)
            )
            determ += int(world.service.status(review_id, tenant_id="tenant-a").model_dump() == status.model_dump())
            if status.state == "approved":
                barred = set(status.review.subject.contributor_ids) | {status.review.requested_by}
                unsafe += int(
                    any(a in barred or a.startswith(("system:", "model:", "agent:")) for a in status.approvals)
                    or len(status.approvals) < status.review.required_approvals
                )
            if by_op[case["id"]] == "decide_after_expiry":
                expiry_ok += int(sum(e.event_type == "expired" for e in events) == 1 and status.state == "expired")
    total = len(suite["cases"])
    metrics = {
        "outcome_agreement": sum(r["passed"] for r in results) / total,
        "forbidden_decision_rejection": sum(r["passed"] and r["got"].startswith("refused:") for r in forbidden)
        / len(forbidden),
        "stale_decision_rejection": sum(r["passed"] and r["got"].startswith("refused:") for r in stale) / len(stale),
        "expiry_enforcement": (expiry_ok if expiry else 0) / len(expiry) if expiry else 0.0,
        "audit_completeness": audited / reviews if reviews else 0.0,
        "approvals_without_independent_review": unsafe,
        "subject_mutations": mutations,
        "determinism": determ / reviews if reviews else 0.0,
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


def render_markdown(report: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    approval = report["approval"]
    approved = approval["status"] == "approved"
    label = "approved" if approved else "proposed"
    verdict = f"MEETS the {label} thresholds" if report["meets_thresholds"] else f"DOES NOT MEET the {label} thresholds"
    status = (
        f"The thresholds were approved by {approval['approved_by']} on {approval['approved_at']} "
        "(scope: these review-corpus thresholds only). "
        if approved
        else "The thresholds are PROPOSED and NOT APPROVED. "
    )
    lines = [
        "# ADS-055: Independent Review Report",
        "",
        f"Generated {stamp} by `make analytics-review-eval`. Corpus `{report['suite_version']}` "
        f"(`{report['corpus_sha256'][:12]}`), rules `{report['rules_version']}`.",
        "",
        f"**Result: {verdict}.** {status}This is not the M5 `separation_of_duties_review` approval; "
        "approving a subject applies, certifies, and promotes nothing.",
        "",
        "## Scope and limits",
        "",
        "- Reviewers are reference-stack tokens with a group claim; there is no real identity provider or group sync.",
        "- Each case runs in a fresh fakes-only stack with hand-written expectations; they show the rules behave as specified.",
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
