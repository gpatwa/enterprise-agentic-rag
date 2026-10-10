"""EA-063 through EA-067 versioning, rollout, drift, and correction tests."""
from datetime import datetime, timedelta, timezone

import pytest

from app.aiops import ComponentRegistry, CorrectionMemory, DriftMonitor, RolloutManager
from packages.platform_contracts.aiops import ComponentVersion, ValidatedCorrection


def test_component_versions_are_immutable_and_rollouts_can_rollback():
    registry = ComponentRegistry()
    registry.register(ComponentVersion(component="model", version="m1", immutable_digest="sha-a"))
    with pytest.raises(ValueError, match="digest"):
        registry.register(ComponentVersion(component="model", version="m1", immutable_digest="sha-b"))
    manager = RolloutManager()
    manager.start_canary("model", "m1", "m2", 10)
    assert manager.rollback("model").active_version == "m1"


def test_drift_and_correction_memory_require_explicit_regression_link():
    assert DriftMonitor().observe("quality", "demo", 0.9, 0.8).alert is True
    memory = CorrectionMemory()
    correction = ValidatedCorrection(
        correction_id="c1", tenant_id="demo", scope="question", source_query_id="q1", approved_by="owner",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), input_fingerprint="in", output_fingerprint="out", regression_case_id="case-1",
    )
    memory.add(correction)
    assert memory.get_for_regression("case-1")[0].correction_id == "c1"
