"""Identity-bound start, status, clarify, and review-resume operations for governed runs (ADS-045).

The service owns no business logic: it derives a deterministic run from the caller's
idempotency key, drives the injected graph runner, and maps the persisted run state to the
public v2 outcome. Run access is always scoped by tenant and purpose; clarification is bound
to the original requester; review decisions go through the control store's identity checks.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError

from app.execution.explanation import Explanation
from app.execution.gateway import ExecutionResult
from app.execution.result_validation import _canonical
from app.runtime.bootstrap import BootstrapRequest
from app.runtime.clarification import ClarificationError, resume_clarification
from app.runtime.control_store import ControlStore, ControlStoreError, LeaseUnavailable, StaleWorkerError
from app.runtime.graph_runner import AgentGraphRunner, GraphRunError
from packages.platform_contracts.agent_runtime import AgentRunState
from packages.platform_contracts.analytics_planning import AnalyticsClarificationState
from packages.platform_contracts.analytics_v2 import (
    AnalyticsAnswerOutcome,
    AnalyticsClaim,
    AnalyticsClarificationChoice,
    AnalyticsClarificationQuestion,
    AnalyticsClarifyOutcome,
    AnalyticsFailedOutcome,
    AnalyticsRefuseOutcome,
    AnalyticsResultTable,
    AnalyticsReviewOutcome,
    AnalyticsVisualization,
)
from packages.platform_contracts.analytics_v2_api import AnalyzeRunResponse
from packages.platform_contracts.security import AnalyticsIdentity

_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class ServiceError(Exception):
    """A request-level failure; `code` is stable and `status` is the HTTP status to use."""

    def __init__(self, status: int, code: str) -> None:
        self.status, self.code = status, code
        super().__init__(code)


@dataclass(frozen=True)
class AnswerMaterial:
    result: ExecutionResult
    explanation: Explanation


class AnswerSource(Protocol):
    def answer_for(self, state: AgentRunState) -> AnswerMaterial | None: ...


class RunnerFactory(Protocol):
    def __call__(self, identity: AnalyticsIdentity, request: BootstrapRequest) -> AgentGraphRunner: ...


StateFactory = Callable[[BootstrapRequest, str, str], AgentRunState]
"""(request, run_id, purpose) -> initial run state; raises ServiceError when no snapshot is usable."""


class GovernedAnalyzeService:
    def __init__(
        self,
        store: ControlStore,
        *,
        runner_factory: RunnerFactory,
        state_factory: StateFactory,
        answers: AnswerSource,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.store, self.runner_factory, self.state_factory, self.answers, self.now = (
            store,
            runner_factory,
            state_factory,
            answers,
            now,
        )

    # ---- operations ----

    def analyze(
        self, identity: AnalyticsIdentity, *, purpose: str, idempotency_key: str, request_text: str
    ) -> AnalyzeRunResponse:
        self._authorize(identity, purpose)
        if not _KEY.match(idempotency_key or ""):
            raise ServiceError(400, "invalid_idempotency_key")
        run_id = hashlib.sha256(
            f"{identity.tenant_id}:{identity.user_id}:{purpose}:{idempotency_key}".encode()
        ).hexdigest()[:32]
        request = BootstrapRequest(
            request_id=f"{_tag(identity)}:{idempotency_key}", request_text=request_text, identity=identity
        )
        existing = self._load(run_id, identity.tenant_id, purpose, missing_ok=True)
        if existing is None:
            state = self.state_factory(request, run_id, purpose)
            try:
                self.runner_factory(identity, request).start(state, owner_id=_owner(), lease_token=_owner())
            except IntegrityError:  # a concurrent duplicate won the create race
                existing = self._load(run_id, identity.tenant_id, purpose)
            except LeaseUnavailable:
                pass
        if existing is not None:
            if (existing.request_text or "").strip() != request_text.strip():
                raise ServiceError(409, "idempotency_key_reused")
            if existing.status == "active":  # recover a run whose worker died; a live lease means "running"
                self._resume(identity, existing)
        return self._respond(identity, self._load(run_id, identity.tenant_id, purpose))

    def status(self, identity: AnalyticsIdentity, *, purpose: str, run_id: str) -> AnalyzeRunResponse:
        self._authorize(identity, purpose)
        return self._respond(identity, self._load(run_id, identity.tenant_id, purpose))

    def clarify(
        self, identity: AnalyticsIdentity, *, purpose: str, run_id: str, ambiguity_code: str, selected_id: str
    ) -> AnalyzeRunResponse:
        self._authorize(identity, purpose)
        state = self._load(run_id, identity.tenant_id, purpose)
        if state.request_id.split(":", 1)[0] != _tag(identity):
            raise ServiceError(403, "not_run_requester")
        if state.status != "waiting_approval" or not state.clarification_state or _review_id(state):
            raise ServiceError(409, "run_not_awaiting_clarification")
        try:
            current = AnalyticsClarificationState.model_validate(state.clarification_state)
            updated = resume_clarification(
                current,
                identity=identity,
                run_id=run_id,
                query_id=current.query_id,
                purpose=purpose,
                ambiguity_code=ambiguity_code,
                selected_id=selected_id,
            )
        except (ClarificationError, ValueError) as exc:
            raise ServiceError(422, "invalid_clarification") from exc
        self._resume(identity, state, {"clarification_state": updated.model_dump(mode="json")})
        return self._respond(identity, self._load(run_id, identity.tenant_id, purpose))

    def decide_review(
        self,
        identity: AnalyticsIdentity,
        *,
        purpose: str,
        run_id: str,
        decision: str,
        plan_fingerprint: str,
        note: str | None,
    ) -> AnalyzeRunResponse:
        self._authorize(identity, purpose)
        state = self._load(run_id, identity.tenant_id, purpose)
        review_id = _review_id(state)
        if state.status != "waiting_approval" or not review_id:
            raise ServiceError(409, "run_not_awaiting_review")
        try:
            self.store.resolve_review(
                review_id,
                tenant_id=identity.tenant_id,
                purpose=purpose,
                identity=identity,
                decision=decision,
                plan_fingerprint=plan_fingerprint,
                note=note,
                now=self.now(),
            )
        except StaleWorkerError as exc:
            raise ServiceError(409, "review_stale") from exc
        except ControlStoreError as exc:
            raise ServiceError(403, "review_not_permitted") from exc
        self._resume(identity, state)
        return self._respond(identity, self._load(run_id, identity.tenant_id, purpose))

    # ---- internals ----

    @staticmethod
    def _authorize(identity: AnalyticsIdentity, purpose: str) -> None:
        if purpose not in identity.purposes:
            raise ServiceError(403, "purpose_not_authorized")

    def _load(self, run_id: str, tenant_id: str, purpose: str, *, missing_ok: bool = False) -> AgentRunState | None:
        try:
            return self.store.load_latest_checkpoint(run_id=run_id, tenant_id=tenant_id, purpose=purpose)
        except ControlStoreError as exc:
            if missing_ok:
                return None
            raise ServiceError(404, "run_not_found") from exc

    def _resume(self, identity: AnalyticsIdentity, state: AgentRunState, payload: dict[str, Any] | None = None) -> None:
        request = BootstrapRequest(
            request_id=state.request_id, request_text=state.request_text or "   ", identity=identity
        )
        try:
            self.runner_factory(identity, request).resume(
                run_id=state.run_id,
                tenant_id=state.tenant_id,
                purpose=state.purpose,
                owner_id=_owner(),
                lease_token=_owner(),
                resume_payload=payload,
            )
        except LeaseUnavailable:
            pass  # another worker is advancing it; the response reports "running"
        except GraphRunError as exc:
            raise ServiceError(409, "run_not_resumable") from exc

    def _respond(self, identity: AnalyticsIdentity, state: AgentRunState) -> AnalyzeRunResponse:
        base = {
            "query_id": state.request_id,
            "tenant_id": state.tenant_id,
            "user_id": identity.user_id,
            "dataset": (state.intent or {}).get("dataset_id") or "unresolved",
            "generated_at": self.now(),
        }
        if state.status == "waiting_approval":
            if _review_id(state):
                review = self.store.get_review(_review_id(state), tenant_id=state.tenant_id, purpose=state.purpose)
                if review.state == "pending":
                    outcome = AnalyticsReviewOutcome(
                        **base,
                        review_id=review.review_id,
                        plan_fingerprint=review.plan_fingerprint,
                        risk_reasons=[(state.approval_state or {}).get("reason") or "human_approval"],
                        expires_at=review.expires_at,
                        allowed_actions=["approve", "reject"],
                    )
                    return AnalyzeRunResponse(run_id=state.run_id, state="waiting_review", outcome=outcome)
                return AnalyzeRunResponse(run_id=state.run_id, state="running")  # decided, resume pending
            clarification = AnalyticsClarificationState.model_validate(state.clarification_state or {})
            outcome = AnalyticsClarifyOutcome(
                **base,
                questions=[
                    AnalyticsClarificationQuestion(
                        id=item.code,
                        prompt=item.prompt,
                        choices=[AnalyticsClarificationChoice(id=c, label=c) for c in item.candidate_ids[:8]],
                        free_text_allowed=False,
                    )
                    for item in clarification.ambiguities
                    if item.code not in clarification.selected_choices
                ]
                or [AnalyticsClarificationQuestion(id="confirm", prompt="Confirm the selection.")],
            )
            return AnalyzeRunResponse(run_id=state.run_id, state="waiting_clarification", outcome=outcome)
        if state.status != "terminal" or state.terminal_outcome is None:
            return AnalyzeRunResponse(run_id=state.run_id, state="running")
        return AnalyzeRunResponse(run_id=state.run_id, state="terminal", outcome=self._terminal(state, base))

    def _terminal(self, state: AgentRunState, base: dict[str, Any]):
        kind = state.terminal_outcome.kind
        codes = [error.code for error in state.errors]
        if kind == "succeeded":
            material = self.answers.answer_for(state)
            if material is None:
                return AnalyticsFailedOutcome(
                    **base, error_code="internal_error", message="The answer is unavailable.", retryable=True
                )
            return _answer(base, state, material)
        if kind == "refused":
            return AnalyticsRefuseOutcome(
                **base, reason_code="policy_restricted", explanation="The request was refused by policy or review."
            )
        if kind == "review_required":
            return AnalyticsRefuseOutcome(
                **base,
                reason_code="stale_metadata",
                explanation="The request could not proceed against current certified context or review.",
                remediation="Resubmit the request.",
            )
        code, message, retryable = _failure(codes, kind)
        return AnalyticsFailedOutcome(**base, error_code=code, message=message, retryable=retryable)


def _answer(base: dict[str, Any], state: AgentRunState, material: AnswerMaterial) -> AnalyticsAnswerOutcome:
    explanation, result = material.explanation, material.result
    viz = explanation.visualization
    answer = (
        " ".join(claim.text for claim in explanation.claims) or "The validated result is returned without narrative."
    )
    contract = ((state.intent or {}).get("semantic_contract") or {}).get("contract_version")
    return AnalyticsAnswerOutcome(
        **base,
        answer=answer,
        explanation_status=explanation.status,
        claims=[AnalyticsClaim(text=c.text, cites=list(c.cites)) for c in explanation.claims],
        result=AnalyticsResultTable(
            columns=list(result.columns),
            rows=[[_canonical(v) for v in row] for row in result.rows],
            row_count=result.row_count,
        ),
        visualization=AnalyticsVisualization(
            kind=viz.kind,
            x_column=viz.x.column_index if viz.x else None,
            y_columns=[b.column_index for b in viz.y],
            semantic_ids=[b.semantic_id for b in ([viz.x] if viz.x else []) + list(viz.y)],
            row_limit=viz.row_limit,
        ),
        evidence={
            "semantic_contract_version": contract,
            "metric_ids": [m["metric_id"] for m in (state.intent or {}).get("metrics", [])],
            "dimension_ids": [g["dimension_id"] for g in (state.intent or {}).get("group_by", [])],
            "result_fingerprint": explanation.result_fingerprint,
        },
    )


def _failure(codes: list[str], kind: str) -> tuple[str, str, bool]:
    if "run_deadline_exceeded" in codes:
        return "query_timeout", "The request exceeded its time budget.", True
    if any(code.startswith(("execution", "execute", "control_query")) for code in codes):
        return "executor_unavailable", "Query execution failed.", True
    if "malformed_model_output" in codes:
        return "planner_unavailable", "The request could not be planned.", True
    if kind == "cancelled":
        return "internal_error", "The run was cancelled.", False
    return "internal_error", "The run failed.", False


def _review_id(state: AgentRunState) -> str | None:
    approval = state.approval_state if isinstance(state.approval_state, dict) else {}
    return approval.get("review_id")


def _tag(identity: AnalyticsIdentity) -> str:
    return hashlib.sha256(identity.user_id.encode()).hexdigest()[:16]


def _owner() -> str:
    return f"api-{hashlib.sha256(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:12]}"
