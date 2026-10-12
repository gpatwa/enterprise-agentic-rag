"""Reference-stack runners for candidate evaluation (ADS-056): sandbox builders and suite adapters.

Everything runs against throwaway stacks. A candidate is applied only inside a sandbox stack (a prompt template
for the intent node, or review flags on a copy of the contract); nothing is written to the registry, the
runtime, or any protected file.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from app.evaluation_gate import EvaluationError
from packages.platform_contracts.candidate_evaluation import SuiteOutcome
from reference_stack import dbt_eval, golden, proposal_eval, triage_eval
from reference_stack.stack import SERVICE_ROOT, ReferenceStack

INDEX = Path(__file__).parent / "evaluation" / "case-index-v1.json"


def load_index() -> dict[str, dict]:
    return json.loads(INDEX.read_text())["cases"]


def protected_paths() -> list[Path]:
    manifest = SERVICE_ROOT.parent.parent / "docs/execution/enterprise-analytics/agentic-data-stack-program.yaml"
    return [
        golden.CORPUS,
        golden.THRESHOLDS,
        triage_eval.CORPUS,
        triage_eval.THRESHOLDS,
        proposal_eval.CORPUS,
        proposal_eval.THRESHOLDS,
        dbt_eval.CORPUS,
        dbt_eval.THRESHOLDS,
        INDEX,
        SERVICE_ROOT / "app/runtime/intent_node.py",
        manifest,
        *sorted((SERVICE_ROOT / "semantic_registry/contracts").glob("*.json")),
    ]


class ReferenceRunners:
    """Full suites are the ones whose thresholds the user has approved: golden, triage, proposals, dbt."""

    # Results depend only on the repo state and the sandbox, so identical runs are shared across instances.
    _cache: dict[tuple[str, tuple[str, ...], str], tuple[SuiteOutcome, ...]] = {}
    _others: dict[tuple[str, tuple[str, ...]], list[SuiteOutcome]] = {}

    def __init__(
        self, stack: ReferenceStack, *, suites: tuple[str, ...] = ("golden", "triage", "proposals", "dbt")
    ) -> None:
        self.stack, self.suites = stack, suites
        digest = hashlib.sha256()
        for path in (golden.THRESHOLDS, triage_eval.THRESHOLDS, proposal_eval.THRESHOLDS, dbt_eval.THRESHOLDS, INDEX):
            digest.update(path.read_bytes())
        digest.update(",".join(suites).encode())
        self.version = digest.hexdigest()[:16]

    def sandbox(self, kind: str, subject_id: str, tenant_id: str) -> dict[str, Any]:
        if kind == "prompt_candidate":
            name, _, version = subject_id.partition("@")
            return {
                "prompt_template": self.stack.prompt_registry()
                .get("prompt", name, version, tenant_id=tenant_id)
                .template_text
            }
        if kind == "change_proposal":
            proposal = self.stack.proposal_service().store.get(subject_id, tenant_id=tenant_id)
            if proposal.operation == "flag_definition_for_review":
                metadata = next(op.value for op in proposal.draft_patch if op.path == "/contract/metadata")
                return {"contract_metadata": metadata}
        return {}

    def targeted(self, case_ids: tuple[str, ...], stack_kwargs: dict[str, Any]) -> SuiteOutcome:
        results = golden.run_golden_cases(set(case_ids), stack_kwargs=stack_kwargs) if case_ids else []
        failed = sorted({r.case_id for r in results if not r.passed})
        return SuiteOutcome(
            suite="golden", scope="targeted", passed=not failed, total=len(results), failed=tuple(failed)
        )

    def full(self, stack_kwargs: dict[str, Any]) -> tuple[SuiteOutcome, ...]:
        key = (self.version, self.suites, json.dumps(stack_kwargs, sort_keys=True, default=str))
        if key not in self._cache:
            outcomes = []
            if "golden" in self.suites:
                report = golden.run_golden(stack_kwargs=stack_kwargs)
                outcomes.append(_outcome("golden", report))
            outcomes.extend(self._other_suites())  # other corpora exercise other subsystems and never take the sandbox
            self._cache[key] = tuple(outcomes)
        return self._cache[key]

    def _other_suites(self) -> list[SuiteOutcome]:
        key = (self.version, self.suites)
        if key not in self._others:
            runners = {
                "triage": triage_eval.run_corpus,
                "proposals": proposal_eval.run_corpus,
                "dbt": dbt_eval.run_corpus,
            }
            self._others[key] = [
                _outcome(name, run(Path(tempfile.mkdtemp(prefix=f"analytics-eval-{name}-"))))
                for name, run in runners.items()
                if name in self.suites
            ]
        return self._others[key]


def _outcome(suite: str, report: dict[str, Any]) -> SuiteOutcome:
    failed = [c["case_id"] for c in report.get("cases", []) if not c["passed"]]
    failed += [f"gate:{name}" for name, gate in report["gates"].items() if not gate["meets"]]
    return SuiteOutcome(
        suite=suite,
        scope="full",
        passed=bool(report["meets_thresholds"]),
        total=len(report.get("cases", [])),
        failed=tuple(failed) if not report["meets_thresholds"] else (),
        thresholds_approved=report["approval"]["status"] == "approved",
    )


__all__ = ["EvaluationError", "ReferenceRunners", "load_index", "protected_paths"]
