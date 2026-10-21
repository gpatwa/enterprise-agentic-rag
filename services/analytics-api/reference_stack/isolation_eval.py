"""ADS-074: security, tenant-isolation, and policy adversarial evaluation across every caller surface (fakes only).

A matrix of hostile probes (another tenant, a missing purpose, the requester approving their own review, an agent deciding a review,
forged and expired tokens) is run against the REST API and the agent-tool surface with real runs in two states (answered and paused
for review). A probe passes only if it is refused AND nothing of the victim's run (its ID, rows, or plan) appears in the response. The
ADS-067 security corpus and the ADS-070 protected cases (policy-denied, tenant-isolation, refusals) are re-run and folded in.
Thresholds are PROPOSED until the user approves them. This is a test matrix, not an independent security review.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from jose import jwt

from app.agent_tools import AgentToolSurface
from packages.platform_contracts.review import REVIEWER_GROUP
from reference_stack import golden, security_eval
from reference_stack import m7_corpus as corpus_module
from reference_stack.stack import AUDIENCE, ISSUER, KEY_ID, build_stack

HERE = Path(__file__).parent / "m7"
THRESHOLDS = HERE / "isolation-thresholds.proposed.json"
PURPOSE = "analytics"
URL = "/api/v2/analytics"
_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
GATE_PLAN = {
    "cross_tenant_leaks": "Policy and tenant-isolation violations 0",
    "purpose_violations": "Policy and tenant-isolation violations 0 (a purpose the caller lacks)",
    "separation_of_duties_violations": "A requester or an agent decides a review: 0",
    "same_tenant_overreach": "A colleague in the same tenant reads another person's run or rows, or decides a review without the role: 0",
    "unauthenticated_successes": "Forged, expired, wrong-audience, or missing tokens that succeed: 0",
    "probe_agreement": "Every hostile probe is refused without leaking the victim's data",
    "security_corpus_gates_met": "ADS-067 security corpus gates met",
    "protected_case_failures": "ADS-070 policy-denied, tenant-isolation, and refusal cases that fail: 0",
}


def _bad_token(stack, kind: str) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "requester",
        "tid": "tenant-a",
        "groups": ["analyst"],
        "purposes": [PURPOSE],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    secret = stack.secret
    if kind == "forged_signature":
        secret = "not-the-issuers-secret"
    elif kind == "expired":
        claims["exp"] = datetime.now(timezone.utc) - timedelta(minutes=5)
    elif kind == "wrong_audience":
        claims["aud"] = "some-other-service"
    elif kind == "wrong_issuer":
        claims["iss"] = "https://evil.example"
    return jwt.encode(claims, secret, algorithm="HS256", headers={"kid": KEY_ID})


def _leaked(text: str, victim: dict[str, Any]) -> bool:
    return any(marker and marker in text for marker in victim["markers"])


def _probe(rows: list, name: str, surface: str, group: str, denied: bool, leaked: bool) -> None:
    rows.append(
        {
            "name": name,
            "surface": surface,
            "group": group,
            "denied": denied,
            "leaked": leaked,
            "passed": denied and not leaked,
        }
    )


def run_matrix(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    main = build_stack("duckdb", root / "main")
    review = build_stack("duckdb", root / "review", review_threshold=1e-9)
    clients = {"main": TestClient(main.app()), "review": TestClient(review.app())}

    def post(stack_name, stack, path, body, token=None, key=None, method="post", params=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if key:
            headers["Idempotency-Key"] = key
        client = clients[stack_name]
        if method == "get":
            return client.get(f"{URL}{path}", params=params, headers=headers)
        return client.post(f"{URL}{path}", json=body, headers=headers)

    requester = main.token("requester")
    answered = post(
        "main",
        main,
        "/analyze",
        {"request_text": "What is total revenue", "purpose": PURPOSE},
        requester,
        "iso-answered-0001",
    ).json()
    paused = post(
        "review",
        review,
        "/analyze",
        {"request_text": "What is total revenue", "purpose": PURPOSE},
        review.token("requester"),
        "iso-paused-00001",
    ).json()
    victim_main = {"markers": [answered["run_id"], "5050"]}
    victim_review = {"markers": [paused["run_id"], paused["outcome"].get("plan_fingerprint") or ""]}
    assert answered["state"] == "terminal" and paused["state"] == "waiting_review"

    def check(name, group, surface, response, victim):
        _probe(rows, name, surface, group, response.status_code >= 400, _leaked(response.text, victim))

    # another tenant, same purpose
    other = main.token("requester", tenant="tenant-b")
    check(
        "read a run of another tenant",
        "cross_tenant",
        "rest",
        post("main", main, f"/runs/{answered['run_id']}", None, other, method="get", params={"purpose": PURPOSE}),
        victim_main,
    )
    check(
        "feedback on a run of another tenant",
        "cross_tenant",
        "rest",
        post(
            "main",
            main,
            f"/runs/{answered['run_id']}/feedback",
            {"purpose": PURPOSE, "verdict": "incorrect", "reason_code": "wrong_metric"},
            other,
            "iso-feedback-0001",
        ),
        victim_main,
    )
    check(
        "clarify a run of another tenant",
        "cross_tenant",
        "rest",
        post(
            "main",
            main,
            f"/runs/{answered['run_id']}/clarify",
            {"purpose": PURPOSE, "ambiguity_code": "time", "selected_id": "created_at"},
            other,
        ),
        victim_main,
    )
    check(
        "decide a review of another tenant",
        "cross_tenant",
        "rest",
        post(
            "review",
            review,
            f"/runs/{paused['run_id']}/review",
            {"purpose": PURPOSE, "decision": "approved", "plan_fingerprint": paused["outcome"]["plan_fingerprint"]},
            review.token("reviewer", tenant="tenant-b"),
        ),
        victim_review,
    )
    check(
        "re-submit the same idempotency key as another tenant",
        "cross_tenant",
        "rest",
        post(
            "main",
            main,
            "/analyze",
            {"request_text": "What is total revenue", "purpose": PURPOSE},
            other,
            "iso-answered-0001",
        ),
        victim_main,
    )
    # the same person's purposes
    narrow = main.token("requester", purposes=("billing",))
    check(
        "read a run under a purpose the caller lacks",
        "purpose",
        "rest",
        post("main", main, f"/runs/{answered['run_id']}", None, narrow, method="get", params={"purpose": PURPOSE}),
        victim_main,
    )
    wide = main.token("requester", purposes=(PURPOSE, "billing"))
    check(
        "read a run under a different purpose than it was made with",
        "purpose",
        "rest",
        post("main", main, f"/runs/{answered['run_id']}", None, wide, method="get", params={"purpose": "billing"}),
        victim_main,
    )
    check(
        "analyze under a purpose the caller lacks",
        "purpose",
        "rest",
        post(
            "main",
            main,
            "/analyze",
            {"request_text": "What is total revenue", "purpose": PURPOSE},
            narrow,
            "iso-purpose-00001",
        ),
        victim_main,
    )
    # separation of duties
    check(
        "the requester approves their own review",
        "duties",
        "rest",
        post(
            "review",
            review,
            f"/runs/{paused['run_id']}/review",
            {"purpose": PURPOSE, "decision": "approved", "plan_fingerprint": paused["outcome"]["plan_fingerprint"]},
            review.token("requester"),
        ),
        victim_review,
    )
    check(
        "an automated caller approves a review",
        "duties",
        "rest",
        post(
            "review",
            review,
            f"/runs/{paused['run_id']}/review",
            {"purpose": PURPOSE, "decision": "approved", "plan_fingerprint": paused["outcome"]["plan_fingerprint"]},
            review.token("agent:svc-bot", groups=("analyst", REVIEWER_GROUP)),  # even with the reviewer role
        ),
        victim_review,
    )
    check(
        "a colleague without the reviewer role approves a review",
        "duties",
        "rest",
        post(
            "review",
            review,
            f"/runs/{paused['run_id']}/review",
            {"purpose": PURPOSE, "decision": "approved", "plan_fingerprint": paused["outcome"]["plan_fingerprint"]},
            review.token("colleague"),
        ),
        victim_review,
    )
    check(
        "the requester holding the reviewer role approves their own review",
        "duties",
        "rest",
        post(
            "review",
            review,
            f"/runs/{paused['run_id']}/review",
            {"purpose": PURPOSE, "decision": "approved", "plan_fingerprint": paused["outcome"]["plan_fingerprint"]},
            review.token("requester", groups=("analyst", REVIEWER_GROUP)),
        ),
        victim_review,
    )
    # the same tenant and purpose: a colleague must not read another person's run or rows (F-05)
    check(
        "a colleague reads another person's answered run",
        "same_tenant",
        "rest",
        post(
            "main",
            main,
            f"/runs/{answered['run_id']}",
            None,
            main.token("colleague"),
            method="get",
            params={"purpose": PURPOSE},
        ),
        victim_main,
    )
    reviewer_read = post(
        "main",
        main,
        f"/runs/{answered['run_id']}",
        None,
        main.token("reviewer"),
        method="get",
        params={"purpose": PURPOSE},
    )
    withheld = (
        reviewer_read.status_code >= 400
        or (reviewer_read.json().get("outcome") or {}).get("reason_code") == "unauthorized"
    )
    _probe(
        rows,
        "a reviewer reads another person's answer rows",
        "rest",
        "same_tenant",
        withheld,
        _leaked(reviewer_read.text, {"markers": ["5050"]}),
    )
    check(
        "approve with a stale plan fingerprint",
        "duties",
        "rest",
        post(
            "review",
            review,
            f"/runs/{paused['run_id']}/review",
            {"purpose": PURPOSE, "decision": "approved", "plan_fingerprint": "0" * 64},
            review.token("reviewer"),
        ),
        victim_review,
    )
    # tokens
    for kind in ("forged_signature", "expired", "wrong_audience", "wrong_issuer"):
        token = _bad_token(main, kind)
        check(
            f"{kind.replace('_', ' ')} token reads a run",
            "auth",
            "rest",
            post("main", main, f"/runs/{answered['run_id']}", None, token, method="get", params={"purpose": PURPOSE}),
            victim_main,
        )
        check(
            f"{kind.replace('_', ' ')} token asks a question",
            "auth",
            "rest",
            post(
                "main",
                main,
                "/analyze",
                {"request_text": "What is total revenue", "purpose": PURPOSE},
                token,
                f"iso-{kind[:6]}-00001",
            ),
            victim_main,
        )
    check(
        "no token reads a run",
        "auth",
        "rest",
        post("main", main, f"/runs/{answered['run_id']}", None, None, method="get", params={"purpose": PURPOSE}),
        victim_main,
    )
    check(
        "malformed bearer token",
        "auth",
        "rest",
        post("main", main, f"/runs/{answered['run_id']}", None, "not.a.jwt", method="get", params={"purpose": PURPOSE}),
        victim_main,
    )

    # agent-tool surface
    main_tools = AgentToolSurface(main.service(), evidence=main.evidence)
    review_tools = AgentToolSurface(review.service(), evidence=review.evidence)
    foreign = main.verifier().verify(other)
    for tool, args in (
        ("analytics.status", {"purpose": PURPOSE, "run_id": answered["run_id"]}),
        ("analytics.evidence", {"purpose": PURPOSE, "run_id": answered["run_id"]}),
    ):
        result = main_tools.call(foreign, {"tool": tool, "arguments": args})
        _probe(
            rows,
            f"{tool} on a run of another tenant",
            "tools",
            "cross_tenant",
            not result.ok,
            _leaked(result.model_dump_json(), victim_main),
        )
    agent = review.verifier().verify(review.token("reviewer")).model_copy(update={"claims": {"act_sub": "agent-1"}})
    result = review_tools.call(
        agent,
        {
            "tool": "analytics.review",
            "arguments": {
                "purpose": PURPOSE,
                "run_id": paused["run_id"],
                "decision": "approved",
                "plan_fingerprint": paused["outcome"]["plan_fingerprint"],
            },
        },
    )
    _probe(
        rows,
        "a delegated agent decides a review",
        "tools",
        "duties",
        not result.ok and result.error and result.error.code == "human_required",
        _leaked(result.model_dump_json(), victim_review),
    )
    return rows


def run_isolation(
    *,
    thresholds: dict[str, Any] | None = None,
    root: Path | None = None,
    security: dict[str, Any] | None = None,
    protected_cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`security` is an ADS-067 corpus report and `protected_cases` the case rows of an ADS-071 run; both are run here when not given."""
    thresholds = thresholds or json.loads(THRESHOLDS.read_text())
    root = root or Path(tempfile.mkdtemp(prefix="analytics-isolation-"))
    rows = run_matrix(root)
    security = security if security is not None else security_eval.run_corpus(root / "security")
    kinds = {"policy_denied", "tenant_isolation", "refuse_no_execution"}
    if protected_cases is None:
        suite, _ = golden.load_suite(
            corpus_module.CORPUS, Path(__file__).parent / "m7" / "e2e-thresholds.proposed.json"
        )
        obs = golden.Observations()
        protected_ids = {c["id"] for c in suite["cases"] if c["kind"] in kinds}
        for engine in ("duckdb", "postgres"):
            golden.run_engine(engine, suite, obs, only=protected_ids)
        protected_cases = [{"passed": r.passed, "kind": r.kind} for r in obs.cases if r.case_id in protected_ids]
    protected = [c for c in protected_cases if c["kind"] in kinds]
    by_group = lambda group: [r for r in rows if r["group"] == group]  # noqa: E731
    metrics = {
        "cross_tenant_leaks": sum(r["leaked"] or not r["denied"] for r in by_group("cross_tenant")),
        "purpose_violations": sum(r["leaked"] or not r["denied"] for r in by_group("purpose")),
        "separation_of_duties_violations": sum(r["leaked"] or not r["denied"] for r in by_group("duties")),
        "unauthenticated_successes": sum(r["leaked"] or not r["denied"] for r in by_group("auth")),
        "same_tenant_overreach": sum(r["leaked"] or not r["denied"] for r in by_group("same_tenant")),
        "probe_agreement": sum(r["passed"] for r in rows) / len(rows),
        "security_corpus_gates_met": 1.0 if security["meets_thresholds"] else 0.0,
        "protected_case_failures": sum(not c["passed"] for c in protected),
    }
    gates = {
        name: {
            "value": metrics[name],
            "op": gate["op"],
            "threshold": gate["value"],
            "meets": bool(_OPS[gate["op"]](metrics[name], gate["value"])),
        }
        for name, gate in thresholds["gates"].items()
    }
    return {
        "packet": "ADS-074",
        "approval": thresholds["approval"],
        "ok": all(g["meets"] for g in gates.values()),
        "gates": gates,
        "gate_plan": GATE_PLAN,
        "samples": {
            "probes": len(rows),
            "security_cases": len(security["cases"]),
            "protected_case_runs": len(protected),
        },
        "open_findings": [f"{f['id']}: {f['title']}" for f in security["findings"] if f["status"] != "resolved"],
        "not_measured": thresholds["not_measured"],
        "probes": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    approval = report["approval"]["status"]
    lines = [
        "# ADS-074: Security, Tenant-Isolation, and Policy Adversarial Evaluation",
        "",
        f"**Result: {'MEETS' if report['ok'] else 'DOES NOT MEET'} the {approval} thresholds.** The thresholds are {approval.upper()}{' and NOT APPROVED' if approval != 'approved' else ''}. "
        "This is a test matrix over a local reference stack, **not an independent security review**; zero violations here is not a statement that none exist.",
        "",
        f"{report['samples']['probes']} hostile probes (REST and agent tools), the {report['samples']['security_cases']}-case ADS-067 corpus, and {report['samples']['protected_case_runs']} protected-case runs from the ADS-070 corpus.",
        "",
        "## Metrics",
        "",
        "| Metric | Measured | Gate | Meets | Plan gate |",
        "|---|---:|---:|:---:|---|",
    ]
    for name, gate in report["gates"].items():
        lines.append(
            f"| `{name}` | {gate['value']:.4g} | {gate['op']} {gate['threshold']} | {'yes' if gate['meets'] else '**NO**'} | {report['gate_plan'][name]} |"
        )
    lines += ["", "## Probes", "", "| Group | Surface | Probe | Refused | Leaked |", "|---|---|---|:---:|:---:|"]
    lines += [
        f"| {p['group']} | {p['surface']} | {p['name']} | {'yes' if p['denied'] else '**NO**'} | {'**YES**' if p['leaked'] else 'no'} |"
        for p in report["probes"]
    ]
    lines += ["", "## Open security findings (not resolved)", ""] + (
        [f"- {f}" for f in report["open_findings"]] or ["None."]
    )
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)
