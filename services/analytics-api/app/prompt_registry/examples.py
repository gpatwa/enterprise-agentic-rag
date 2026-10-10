"""Build example candidates from recorded feedback (ADS-054): references and fingerprints, never text."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.prompt_registry.store import PromptRegistry, RegistryError
from app.runtime.control_store import ControlStoreError
from app.runtime.evidence_store import EvidenceNotFoundError, EvidenceStore
from app.runtime.feedback_store import FeedbackNotFoundError, FeedbackStore
from packages.platform_contracts.prompt_registry import ExampleCandidate, candidate_version, content_fingerprint

EXAMPLE_NAME = "intent-examples"
_QUALIFYING_VERDICTS = {"incorrect", "partially_correct"}


class ExampleCandidateService:
    def __init__(
        self,
        control_store: Any,
        evidence_store: EvidenceStore,
        feedback_store: FeedbackStore,
        registry: PromptRegistry,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.control, self.evidence, self.feedback, self.registry, self.now = (
            control_store,
            evidence_store,
            feedback_store,
            registry,
            now,
        )

    def from_feedback(self, feedback_id: str, *, tenant_id: str) -> tuple[ExampleCandidate, bool]:
        """Register a candidate example for a corrected run. It records where the example came from, not what was asked."""
        try:
            feedback = self.feedback.get(feedback_id, tenant_id=tenant_id)
            envelope = self.evidence.get(feedback.run_id, tenant_id=tenant_id, purpose=feedback.purpose)
            state = self.control.load_latest_checkpoint(
                run_id=feedback.run_id, tenant_id=tenant_id, purpose=feedback.purpose
            )
        except (FeedbackNotFoundError, EvidenceNotFoundError, ControlStoreError) as exc:
            raise RegistryError("feedback, evidence, or run is not available") from exc
        if feedback.verdict not in _QUALIFYING_VERDICTS or feedback.correction is None:
            raise RegistryError("an example needs an incorrect verdict with a correction naming a certified ID")
        if not state.request_text:
            raise RegistryError("the run has no request to fingerprint")
        fields = dict(
            name=EXAMPLE_NAME,
            tenant_id=tenant_id,
            source_run_id=feedback.run_id,
            source_feedback_id=feedback.feedback_id,
            source_evidence_fingerprint=envelope.content_fingerprint,
            request_fingerprint=hashlib.sha256(state.request_text.strip().encode()).hexdigest(),
            intent_fingerprint=envelope.intent_fingerprint,
            semantic_contract=envelope.semantic_contract,
            correction=feedback.correction,
            created_at=self.now(),
        )
        seed = ExampleCandidate(**fields, version="candidate-000000000000", content_fingerprint="0" * 64)
        version = candidate_version(content_fingerprint(seed.model_copy(update={"version": "candidate-000000000000"})))
        final = seed.model_copy(update={"version": version})
        return self.registry.register_example(
            final.model_copy(update={"content_fingerprint": content_fingerprint(final)})
        )
