"""Smoke journeys over the reference stack: one per dialect, plus a cross-dialect parity check."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from app.execution import validate_result
from app.runtime.evidence_store import record_terminal_evidence
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from reference_stack.fakes import PURPOSE
from reference_stack.stack import Engine, ReferenceStack, build_stack, fingerprint_rows

URL = "/api/v2/analytics"


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class JourneyReport:
    engine: str
    steps: list[Step] = field(default_factory=list)
    answer_rows_fingerprint: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(step.ok for step in self.steps)


def _headers(stack: ReferenceStack, user: str, key: str | None = None, **kwargs) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {stack.token(user, **kwargs)}"}
    return {**headers, "Idempotency-Key": key} if key else headers


def run_journey(engine: Engine) -> JourneyReport:
    report = JourneyReport(engine)

    def check(name: str, condition: bool, detail: str = "") -> bool:
        report.steps.append(Step(name, bool(condition), "" if condition else detail))
        return bool(condition)

    stack = build_stack(engine)
    client = TestClient(stack.app())
    body = {"request_text": "Show monthly revenue", "purpose": PURPOSE}

    check("unauthenticated request is refused", client.post(f"{URL}/analyze", json=body).status_code == 401)
    check(
        "unauthorized purpose is refused",
        client.post(
            f"{URL}/analyze", json=body, headers=_headers(stack, "requester", "key-00000000", purposes=("billing",))
        ).status_code
        == 403,
    )

    first = client.post(f"{URL}/analyze", json=body, headers=_headers(stack, "requester", "key-00000001")).json()
    answer = first.get("outcome") or {}
    grounded = (
        first.get("state") == "terminal"
        and answer.get("outcome") == "answer"
        and answer.get("explanation_status") == "grounded"
    )
    if check("monthly revenue returns a grounded answer", grounded, str(first)[:200]):
        rows = answer["result"]["rows"]
        check(
            "answer has three monthly rows with a bar/line spec",
            len(rows) == 3 and answer["visualization"]["kind"] == "line",
            str(rows),
        )
        report.answer_rows_fingerprint = fingerprint_rows(rows)
        replay = client.post(f"{URL}/analyze", json=body, headers=_headers(stack, "requester", "key-00000001")).json()
        check(
            "idempotent replay returns the same run and fingerprint",
            replay["run_id"] == first["run_id"]
            and replay["outcome"]["evidence"]["result_fingerprint"] == answer["evidence"]["result_fingerprint"],
        )
        _seal(stack, first["run_id"], check)
        _feedback_step(stack, client, first["run_id"], check)

    by_status = client.post(
        f"{URL}/analyze",
        json={**body, "request_text": "Revenue by status"},
        headers=_headers(stack, "requester", "key-00000002"),
    ).json()
    check(
        "revenue by status returns two groups",
        (by_status.get("outcome") or {}).get("result", {}).get("row_count") == 2,
        str(by_status)[:200],
    )
    total = client.post(
        f"{URL}/analyze",
        json={**body, "request_text": "What is total revenue"},
        headers=_headers(stack, "requester", "key-00000003"),
    ).json()
    check(
        "ungrouped total renders as a stat",
        (total.get("outcome") or {}).get("visualization", {}).get("kind") == "stat",
        str(total)[:200],
    )
    unknown = client.post(
        f"{URL}/analyze",
        json={**body, "request_text": "Tell me a joke"},
        headers=_headers(stack, "requester", "key-00000004"),
    ).json()
    check(
        "an unsupported question fails safely without a result",
        (unknown.get("outcome") or {}).get("outcome") == "failed" and "result" not in unknown["outcome"],
        str(unknown)[:200],
    )

    _review_journey(engine, report.answer_rows_fingerprint, check)
    return report


def seal_run(stack: ReferenceStack, run_id: str) -> bool:
    """Re-validate and seal a succeeded run; True when a verified, value-free envelope exists."""
    state = stack.control.load_latest_checkpoint(run_id=run_id, tenant_id="tenant-a", purpose=PURPOSE)
    intent = AnalyticalIntent.model_validate(state.intent)
    contract = stack.contracts.get_certified(
        intent.semantic_contract.contract_id, intent.semantic_contract.contract_version
    ).contract
    plan = stack.plans.get(state.tenant_id, run_id, state.compiled_plan_reference)
    result = stack.results.get(state.tenant_id, run_id, state.execution_reference)
    validation = validate_result(
        result, plan, intent, contract, control_totals=stack.control_totals(None, intent, contract)
    )
    record_terminal_evidence(stack.control, stack.evidence, state, validation=validation)
    sealed = stack.evidence.get(run_id, tenant_id=state.tenant_id, purpose=PURPOSE)
    return (
        sealed.terminal_kind == "succeeded"
        and sealed.result is not None
        and sealed.policy is not None
        and sealed.cost is not None
        and stack.evidence.verify_chain(state.tenant_id) >= 1
        and "sales_orders" not in sealed.model_dump_json()
    )


def _seal(stack: ReferenceStack, run_id: str, check) -> None:
    check("terminal run is sealed in a verified evidence chain", seal_run(stack, run_id))


def _feedback_step(stack: ReferenceStack, client: TestClient, run_id: str, check) -> None:
    body = {"purpose": PURPOSE, "verdict": "incorrect", "reason_code": "wrong_time_range"}
    headers = _headers(stack, "analyst", "fb-smoke-0001")
    first = client.post(f"{URL}/runs/{run_id}/feedback", json=body, headers=headers)
    envelope = stack.evidence.get(run_id, tenant_id="tenant-a", purpose=PURPOSE)
    check(
        "feedback binds to the run's sealed evidence",
        first.status_code == 201 and first.json()["evidence_fingerprint"] == envelope.content_fingerprint,
        first.text[:160],
    )
    again = client.post(f"{URL}/runs/{run_id}/feedback", json=body, headers=headers)
    check(
        "feedback replay is idempotent",
        again.status_code == 200 and again.json()["feedback_id"] == first.json().get("feedback_id"),
    )


def _review_journey(engine: Engine, expected_rows: str | None, check) -> None:
    stack = build_stack(engine, review_threshold=1e-9)
    client = TestClient(stack.app())
    body = {"request_text": "Show monthly revenue", "purpose": PURPOSE}
    paused = client.post(f"{URL}/analyze", json=body, headers=_headers(stack, "requester", "key-00000010")).json()
    outcome = paused.get("outcome") or {}
    if not check(
        "an expensive plan pauses for human review", paused.get("state") == "waiting_review", str(paused)[:200]
    ):
        return
    decision: dict[str, Any] = {
        "purpose": PURPOSE,
        "decision": "approved",
        "plan_fingerprint": outcome["plan_fingerprint"],
    }
    url = f"{URL}/runs/{paused['run_id']}/review"
    check(
        "the requester cannot approve their own plan",
        client.post(url, json=decision, headers=_headers(stack, "requester")).status_code == 403,
    )
    approved = client.post(url, json=decision, headers=_headers(stack, "reviewer")).json()
    answer = approved.get("outcome") or {}
    check("a different reviewer approves and the run answers", answer.get("outcome") == "answer", str(approved)[:200])
    if expected_rows and answer.get("outcome") == "answer":
        check(
            "approved answer matches the unreviewed answer", fingerprint_rows(answer["result"]["rows"]) == expected_rows
        )


def run_all(engines: tuple[Engine, ...] = ("duckdb", "postgres")) -> dict[str, Any]:
    reports = [run_journey(engine) for engine in engines]
    parity = None
    if len(reports) == 2 and all(r.answer_rows_fingerprint for r in reports):
        parity = reports[0].answer_rows_fingerprint == reports[1].answer_rows_fingerprint
    return {
        "ok": all(r.ok for r in reports) and parity is not False,
        "cross_dialect_rows_identical": parity,
        "journeys": [asdict(r) | {"ok": r.ok} for r in reports],
    }
