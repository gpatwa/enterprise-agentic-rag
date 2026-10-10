"""Deterministic probe used to verify harness controls before ADS-023."""
from __future__ import annotations

import hashlib
import json

from packages.platform_contracts.determinism import DeterministicControls
from packages.platform_contracts.harness import HarnessReport, HarnessScenario


def build_deterministic_report(
    scenario: HarnessScenario, controls: DeterministicControls
) -> HarnessReport:
    tokens = max(1, (len(scenario.request) + 3) // 4)
    cost = tokens / 1_000
    controls.budget.consume(tokens, cost)
    run_id = controls.ids.next("run")
    logical_time = controls.clock.now().isoformat()
    random_sample = controls.random.randint(0, 1_000_000)
    semantic_payload = {
        "scenario": scenario.model_dump(mode="json"),
        "run_id": run_id, "logical_time": logical_time,
        "random_sample": random_sample, "tokens_used": controls.budget.tokens_used,
        "cost_units": controls.budget.cost_units,
    }
    semantic_fingerprint = hashlib.sha256(
        json.dumps(semantic_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return HarnessReport(
        scenario_id=scenario.scenario_id, scenario_digest=scenario.fixture_digest,
        semantic_fingerprint=semantic_fingerprint, run_id=run_id,
        logical_time=logical_time, random_sample=random_sample,
        tokens_used=controls.budget.tokens_used, cost_units=controls.budget.cost_units,
    )
