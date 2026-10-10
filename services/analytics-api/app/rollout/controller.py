"""Shadow, canary, promotion, and automatic rollback of an approved prompt candidate (ADS-057).

The controller only advances a candidate that has an approved independent review (ADS-055, still fresh) and a
passing evaluation (ADS-056) of its exact content, under an *approved* rollout policy. Promotion creates the next
released registry version and appends an active-version pointer; rollback only appends (a reverted pointer and an
event). Nothing is deleted, and nothing in the runtime reads the registry or the pointer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.evaluation_gate import EvaluationService
from app.prompt_registry import PromptRegistry
from app.review import ReviewError, ReviewService, is_automated
from app.rollout.observers import Observers
from app.rollout.store import RolloutStore, RolloutStoreError
from packages.platform_contracts.prompt_registry import PromptTemplate
from packages.platform_contracts.rollout import RolloutPolicy, RolloutRecord, RolloutState, RolloutStatus
from packages.platform_contracts.security import AnalyticsIdentity

SYSTEM_ACTOR = "system:rollout-controller"


class RolloutError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def policy_fingerprint(policy: RolloutPolicy) -> str:
    return hashlib.sha256(
        json.dumps(policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class RolloutController:
    def __init__(
        self,
        store: RolloutStore,
        reviews: ReviewService,
        evaluations: EvaluationService,
        registry: PromptRegistry,
        observers: Observers,
        policy: RolloutPolicy,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.store, self.reviews, self.evaluations, self.registry = store, reviews, evaluations, registry
        self.observers, self.policy, self.now = observers, policy, now

    # ---- operations ----

    def start(
        self, identity: AnalyticsIdentity, *, purpose: str, subject_id: str, kind: str = "prompt_candidate"
    ) -> RolloutStatus:
        self._require_policy()
        if purpose not in identity.purposes:
            raise RolloutError("purpose_not_authorized")
        if is_automated(identity.user_id):
            raise RolloutError("automated_identity")
        if kind != "prompt_candidate":
            raise RolloutError("not_promotable")
        tenant = identity.tenant_id
        try:
            subject = self.reviews.resolver.resolve(kind, subject_id, tenant_id=tenant)
        except ReviewError as exc:
            raise RolloutError(exc.code) from exc
        candidate = self._candidate(subject_id, tenant)
        policy_fp = policy_fingerprint(self.policy)
        rollout_id = hashlib.sha256(
            f"{tenant}:{subject_id}:{subject.content_fingerprint}:{policy_fp}".encode()
        ).hexdigest()[:32]
        try:
            return self.status(
                rollout_id, tenant_id=tenant
            )  # the same candidate under the same policy is the same rollout
        except RolloutError:
            pass
        gate = self._gate_failure(kind, subject_id, subject.content_fingerprint, tenant)
        if gate:
            raise RolloutError(gate)
        name = candidate.name
        if self.store.active_version(name) is None:
            self.store.append_pointer(name, candidate.parent_version, None, "baseline", self.now())
        if self.store.active_version(name) != candidate.parent_version:
            raise RolloutError("stale_parent")  # the candidate was derived from a version that is no longer active
        review = next(
            r
            for r in self.reviews.store.for_subject(kind, subject_id, subject.content_fingerprint, tenant_id=tenant)
            if self.reviews.status(r.review_id, tenant_id=tenant).state == "approved"
        )
        evaluation = self.evaluations.passing_record(kind, subject_id, subject.content_fingerprint, tenant_id=tenant)
        policy_fp = policy_fingerprint(self.policy)
        rollout_id = hashlib.sha256(
            f"{tenant}:{subject_id}:{subject.content_fingerprint}:{policy_fp}".encode()
        ).hexdigest()[:32]
        record = RolloutRecord(
            rollout_id=rollout_id,
            tenant_id=tenant,
            purpose=purpose,
            subject_id=subject_id,
            subject_fingerprint=subject.content_fingerprint,
            prompt_name=name,
            baseline_version=candidate.parent_version,
            review_id=review.review_id,
            evaluation_id=evaluation.evaluation_id,
            policy_version=self.policy.policy_version,
            policy_fingerprint=policy_fp,
            started_by=identity.user_id,
            created_at=self.now(),
        )
        if self.store.create(record):
            self.store.append_event(
                tenant, rollout_id, "started", identity.user_id, {"baseline": record.baseline_version}, self.now()
            )
        return self.status(rollout_id, tenant_id=tenant)

    def advance(self, rollout_id: str, *, tenant_id: str) -> RolloutStatus:
        """Do the next stage: shadow, then each canary fraction. A failed check rolls back automatically."""
        self._require_policy()
        status = self.status(rollout_id, tenant_id=tenant_id)
        if status.state in {"promoted", "rolled_back"}:
            return status
        lost = self._gate_failure(
            "prompt_candidate", status.record.subject_id, status.record.subject_fingerprint, tenant_id
        )
        if lost:
            return self.rollback(rollout_id, tenant_id=tenant_id, reason=f"gate_lost:{lost}")
        candidate = self._candidate(status.record.subject_id, tenant_id)
        if status.state == "evaluated":
            baseline = self.registry.get(
                "prompt", status.record.prompt_name, status.record.baseline_version, tenant_id=tenant_id
            )
            result = self.observers.shadow(candidate.template_text, baseline.template_text)
            if result.agreement < self.policy.shadow_min_agreement:
                return self.rollback(
                    rollout_id,
                    tenant_id=tenant_id,
                    reason="shadow_disagreement",
                    detail={"agreement": round(result.agreement, 4), "total": result.total},
                )
            self.store.append_event(
                tenant_id,
                rollout_id,
                "shadow_passed",
                SYSTEM_ACTOR,
                {"agreement": round(result.agreement, 4), "total": result.total},
                self.now(),
            )
        else:
            remaining = [f for f in self.policy.canary_fractions if f not in status.canary_passed]
            if remaining:
                fraction = remaining[0]
                result = self.observers.canary(candidate.template_text, fraction)
                if result.error_rate > self.policy.canary_max_error_rate:
                    return self.rollback(
                        rollout_id,
                        tenant_id=tenant_id,
                        reason=f"canary_regression:{fraction}",
                        detail={"requests": result.requests, "errors": result.errors},
                    )
                self.store.append_event(
                    tenant_id,
                    rollout_id,
                    "canary_passed",
                    SYSTEM_ACTOR,
                    {"fraction": fraction, "requests": result.requests, "errors": result.errors},
                    self.now(),
                )
        return self.status(rollout_id, tenant_id=tenant_id)

    def promote(self, rollout_id: str, *, tenant_id: str) -> RolloutStatus:
        """Create the next released version and move the active pointer. Needs every canary stage passed."""
        self._require_policy()
        status = self.status(rollout_id, tenant_id=tenant_id)
        if status.state == "promoted":
            return status
        if status.state == "rolled_back":
            raise RolloutError("rolled_back")
        if status.state != "canary" or set(status.canary_passed) != set(self.policy.canary_fractions):
            raise RolloutError("canary_incomplete")
        lost = self._gate_failure(
            "prompt_candidate", status.record.subject_id, status.record.subject_fingerprint, tenant_id
        )
        if lost:
            return self.rollback(rollout_id, tenant_id=tenant_id, reason=f"gate_lost:{lost}")
        candidate = self._candidate(status.record.subject_id, tenant_id)
        released = self.registry.release_promoted(candidate, promotion_id=rollout_id)
        self.store.append_pointer(status.record.prompt_name, released.version, rollout_id, "promoted", self.now())
        self.store.append_event(
            tenant_id, rollout_id, "promoted", SYSTEM_ACTOR, {"released_version": released.version}, self.now()
        )
        return self.status(rollout_id, tenant_id=tenant_id)

    def monitor(self, rollout_id: str, *, tenant_id: str) -> RolloutStatus:
        """Observe a promoted version; roll back automatically if it regresses."""
        self._require_policy()
        status = self.status(rollout_id, tenant_id=tenant_id)
        if status.state != "promoted":
            raise RolloutError("not_promoted")
        released = self.registry.get(
            "prompt", status.record.prompt_name, status.released_version or "", tenant_id=tenant_id
        )
        result = self.observers.monitor(released.template_text)
        if result.error_rate > self.policy.monitor_max_error_rate:
            return self.rollback(
                rollout_id,
                tenant_id=tenant_id,
                reason="monitor_regression",
                detail={"requests": result.requests, "errors": result.errors},
            )
        self.store.append_event(
            tenant_id,
            rollout_id,
            "monitor_ok",
            SYSTEM_ACTOR,
            {"requests": result.requests, "errors": result.errors},
            self.now(),
        )
        return self.status(rollout_id, tenant_id=tenant_id)

    def rollback(
        self, rollout_id: str, *, tenant_id: str, reason: str, actor: str = SYSTEM_ACTOR, detail: dict | None = None
    ) -> RolloutStatus:
        """Stop the rollout. Only appends: a reverted pointer (if it had been promoted) and an event."""
        status = self.status(rollout_id, tenant_id=tenant_id)
        if status.state == "rolled_back":
            return status
        record = status.record
        if status.state == "promoted":
            self.store.append_pointer(
                record.prompt_name, record.baseline_version, rollout_id, f"rollback:{reason}", self.now()
            )
        self.store.append_event(
            tenant_id, rollout_id, "rolled_back", actor, {"reason": reason, **(detail or {})}, self.now()
        )
        return self.status(rollout_id, tenant_id=tenant_id)

    def status(self, rollout_id: str, *, tenant_id: str) -> RolloutStatus:
        try:
            record = self.store.get(rollout_id, tenant_id=tenant_id)
        except RolloutStoreError as exc:
            raise RolloutError("rollout_not_found") from exc
        events = self.store.events(rollout_id, tenant_id=tenant_id)
        state: RolloutState = "evaluated"
        canary: list[float] = []
        released = reason = None
        for event in events:
            if event.event_type == "shadow_passed":
                state = "shadow"
            elif event.event_type == "canary_passed":
                state = "canary"
                canary.append(float(event.detail["fraction"]))
            elif event.event_type == "promoted":
                state, released = "promoted", str(event.detail["released_version"])
            elif event.event_type == "rolled_back":
                state, reason = "rolled_back", str(event.detail.get("reason", ""))
        return RolloutStatus(
            record=record,
            state=state,
            events=events,
            canary_passed=tuple(canary),
            released_version=released,
            rollback_reason=reason,
        )

    def active_version(self, prompt_name: str) -> str | None:
        return self.store.active_version(prompt_name)

    # ---- internals ----

    def _require_policy(self) -> None:
        if self.policy.approval.status != "approved":
            raise RolloutError("rollout_policy_not_approved")

    def _candidate(self, subject_id: str, tenant_id: str) -> PromptTemplate:
        name, _, version = subject_id.partition("@")
        entry = self.registry.get("prompt", name, version, tenant_id=tenant_id)
        if entry.status != "candidate":  # type: ignore[union-attr]
            raise RolloutError("not_promotable")
        return entry  # type: ignore[return-value]

    def _gate_failure(self, kind: str, subject_id: str, fingerprint: str, tenant_id: str) -> str | None:
        """The first gate that no longer holds: review, its freshness, or the evaluation."""
        if not self.reviews.is_approved(kind, subject_id, fingerprint, tenant_id=tenant_id):
            return "review_not_approved"
        approved_at = self.reviews.approval_time(kind, subject_id, fingerprint, tenant_id=tenant_id)
        if approved_at is None or self.now() - approved_at > timedelta(hours=self.policy.approval_max_age_hours):
            return "approval_stale"
        if self.evaluations.passing_record(kind, subject_id, fingerprint, tenant_id=tenant_id) is None:
            return "evaluation_not_passed"
        return None
