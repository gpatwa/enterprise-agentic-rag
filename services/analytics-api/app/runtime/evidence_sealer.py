"""Seal a terminal run into its evidence envelope from the service path (ADS-050).

ADS-042 built the envelope and store; nothing in the v2 service called them. The sealer closes
that gap so feedback (and later review and replay) can bind to sealed evidence. Sealing is
idempotent and never changes the response a caller already received.
"""

from __future__ import annotations

import threading
from typing import Any

from app.runtime.evidence_store import EvidenceStore, record_terminal_evidence
from packages.platform_contracts.agent_runtime import AgentRunState
from packages.platform_contracts.evidence import EvidenceEnvelope


class ValidationReportStore:
    """Process-local, run-scoped handoff of the result-validation report to the sealer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reports: dict[tuple[str, str], Any] = {}

    def put(self, tenant_id: str, run_id: str, report: Any) -> None:
        with self._lock:
            self._reports[(tenant_id, run_id)] = report

    def get(self, tenant_id: str, run_id: str) -> Any | None:
        with self._lock:
            return self._reports.get((tenant_id, run_id))


class EvidenceSealer:
    def __init__(self, control_store: Any, evidence_store: EvidenceStore, reports: ValidationReportStore) -> None:
        self.control, self.evidence, self.reports = control_store, evidence_store, reports

    def seal(self, state: AgentRunState) -> EvidenceEnvelope | None:
        """Seal a terminal run (idempotent); None when the run is not terminal or cannot be sealed."""
        if state.status != "terminal" or state.terminal_outcome is None:
            return None
        report = self.reports.get(state.tenant_id, state.run_id)
        try:
            record_terminal_evidence(self.control, self.evidence, state, validation=report)
        except Exception:  # noqa: BLE001 - an unsealable run simply has no evidence for feedback to bind to.
            return None
        return self.evidence.get(state.run_id, tenant_id=state.tenant_id, purpose=state.purpose)
