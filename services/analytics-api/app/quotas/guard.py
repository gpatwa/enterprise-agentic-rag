"""A quota-enforcing wrapper around the governed analyze service (ADS-066).

Cost-bearing operations (analyze, clarify, review: each can execute a query) are admitted against the tenant's quota *before*
anything runs, so an exhausted tenant costs the platform nothing. Reads (status) are not metered. After a terminal outcome the
sealed evidence supplies the cost, which is attributed to the tenant (by purpose and dialect) exactly once per run.
"""

from __future__ import annotations

import time
from typing import Any

from app.observability.core import run_ref
from app.quotas.manager import QuotaManager, SloTracker
from app.runtime.analyze_service import GovernedAnalyzeService, ServiceError
from app.runtime.evidence_store import EvidenceNotFoundError


class QuotaGuardedService:
    def __init__(
        self,
        service: GovernedAnalyzeService,
        quotas: QuotaManager,
        slo: SloTracker,
        evidence_store: Any = None,
        *,
        dialect: str | None = None,
    ) -> None:
        self._service, self.quotas, self.slo, self._evidence = service, quotas, slo, evidence_store
        self._dialect = dialect  # the warehouse this deployment executes on, for cost attribution

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)

    def _metered(self, identity, purpose: str, run_id: str, call):
        admission = self.quotas.admit(identity.tenant_id)
        if not admission.allowed:
            raise ServiceError(429, admission.code)
        started = time.perf_counter()
        ok, response = True, None
        try:
            response = call()
            ok = not (response.outcome is not None and response.outcome.outcome == "failed")
            return response
        except ServiceError as exc:
            ok = exc.status < 500  # a refusal the caller caused is not a service failure
            raise
        except Exception:
            ok = False
            raise
        finally:
            cost, dialect = self._attributable_cost(identity, purpose, run_id, response)
            self.quotas.finish(
                identity.tenant_id, run_ref=run_ref(run_id), cost_units=cost, purpose=purpose, dialect=dialect
            )
            self.slo.record(identity.tenant_id, ok=ok, latency_seconds=time.perf_counter() - started)

    def _attributable_cost(self, identity, purpose, run_id, response) -> tuple[float, str | None]:
        if response is None or response.state != "terminal" or self._evidence is None:
            return 0.0, None
        try:
            envelope = self._evidence.get(run_id, tenant_id=identity.tenant_id, purpose=purpose)
        except EvidenceNotFoundError:
            return 0.0, self._dialect
        cost = envelope.cost
        spent = (cost.observed_cost_units or cost.estimated_cost_units or 0.0) if cost else 0.0
        return float(spent), self._dialect

    def analyze(self, identity, *, purpose, idempotency_key, request_text):
        run_id = GovernedAnalyzeService.derive_run_id(identity, purpose, idempotency_key)
        return self._metered(
            identity,
            purpose,
            run_id,
            lambda: self._service.analyze(
                identity, purpose=purpose, idempotency_key=idempotency_key, request_text=request_text
            ),
        )

    def clarify(self, identity, *, purpose, run_id, ambiguity_code, selected_id):
        return self._metered(
            identity,
            purpose,
            run_id,
            lambda: self._service.clarify(
                identity, purpose=purpose, run_id=run_id, ambiguity_code=ambiguity_code, selected_id=selected_id
            ),
        )

    def decide_review(self, identity, *, purpose, run_id, decision, plan_fingerprint, note):
        return self._metered(
            identity,
            purpose,
            run_id,
            lambda: self._service.decide_review(
                identity,
                purpose=purpose,
                run_id=run_id,
                decision=decision,
                plan_fingerprint=plan_fingerprint,
                note=note,
            ),
        )
