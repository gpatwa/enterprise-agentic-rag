"""Simulated observers for rollouts on the reference stack (ADS-057).

There is no live traffic. Shadow compares scripted intents for a pinned request set; canary and monitor serve a
deterministic slice of that set through sandbox stacks and count wrong answers. Faults can be injected to prove
that rollback triggers. This demonstrates the controller's logic, not production behaviour.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from fastapi.testclient import TestClient

from app.rollout import CanaryResult, ShadowResult
from packages.platform_contracts.prompt_registry import render
from packages.platform_contracts.rollout import RolloutPolicy
from reference_stack import golden
from reference_stack.fakes import PURPOSE, ScriptedIntentClient
from reference_stack.stack import build_stack

POLICY = Path(__file__).parent / "rollout" / "rollout-policy.proposed.json"
URL = "/api/v2/analytics"


def load_policy(path: Path = POLICY) -> RolloutPolicy:
    return RolloutPolicy.model_validate_json(path.read_text())


def approved_for_test(policy: RolloutPolicy) -> RolloutPolicy:
    """A copy marked approved by the test harness. The repository's policy stays proposed."""
    approval = policy.approval.model_copy(
        update={"status": "approved", "approved_by": "test-harness", "approved_at": "2026-10-10"}
    )
    return policy.model_copy(update={"approval": approval})


class ReferenceObservers:
    def __init__(
        self, *, shadow_fault: bool = False, canary_faults: dict[float, int] | None = None, monitor_fault: int = 0
    ) -> None:
        suite, _ = golden.load_suite()
        self.items = [c for c in suite["cases"] if c["kind"] in {"answer", "refuse_no_execution"}]
        self.shadow_fault, self.canary_faults, self.monitor_fault = shadow_fault, canary_faults or {}, monitor_fault
        self._stacks: dict[str, tuple] = {}
        self._calls = 0

    def shadow(self, candidate_text: str, baseline_text: str) -> ShadowResult:
        agreeing = 0
        for index, item in enumerate(self.items):
            intents = [self._intent(text, item["question"], index) for text in (candidate_text, baseline_text)]
            agreeing += int(intents[0] == intents[1])
        if self.shadow_fault:
            agreeing = max(0, agreeing - 2)
        return ShadowResult(total=len(self.items), agreeing=agreeing)

    def canary(self, candidate_text: str, fraction: float) -> CanaryResult:
        ordered = sorted(self.items, key=lambda c: hashlib.sha256(c["question"].encode()).hexdigest())
        chosen = ordered[: max(1, math.ceil(fraction * len(ordered)))]
        errors = sum(not self._served_correctly(candidate_text, item) for item in chosen)
        return CanaryResult(requests=len(chosen), errors=errors + self.canary_faults.get(fraction, 0))

    def monitor(self, released_text: str) -> CanaryResult:
        errors = sum(not self._served_correctly(released_text, item) for item in self.items)
        return CanaryResult(requests=len(self.items), errors=errors + self.monitor_fault)

    # ---- internals ----

    def _intent(self, text: str, question: str, index: int) -> dict:
        client = ScriptedIntentClient(f"shadow-{index}")
        prompt = render(text, tenant_id="tenant-a", context_json="[]", request_json=json.dumps(question))
        return client.complete_json(prompt=prompt, schema={}, max_tokens=1_024)

    def _served_correctly(self, text: str, item: dict) -> bool:
        if text not in self._stacks:
            stack = build_stack("duckdb", prompt_template=text)
            self._stacks[text] = (stack, TestClient(stack.app()))
        stack, client = self._stacks[text]
        self._calls += 1
        outcome = (
            client.post(
                f"{URL}/analyze",
                json={"request_text": item["question"], "purpose": PURPOSE},
                headers={
                    "Authorization": f"Bearer {stack.token('requester')}",
                    "Idempotency-Key": f"rollout-obs-{self._calls:06d}",
                },
            )
            .json()
            .get("outcome")
            or {}
        )
        if item["kind"] == "answer":
            return (
                outcome.get("outcome") == "answer"
                and golden.canonical_rows((outcome.get("result") or {}).get("rows")) == item["expect_rows"]
            )
        return outcome.get("outcome") in {"failed", "refuse"} and "result" not in outcome
