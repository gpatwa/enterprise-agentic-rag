"""Bounded, deterministic evaluation of governed graph outcomes and gate order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.runtime.graph_runner import AgentGraphRunner, GraphRunResult
from packages.platform_contracts.agent_runtime import AgentRunState, TerminalKind


@dataclass(frozen=True)
class GraphEvaluationCase:
    case_id: str
    build_state: Callable[[], AgentRunState]
    expected_outcome: TerminalKind | None
    required_gate_order: tuple[str, ...] = ()
    run: Callable[[AgentGraphRunner], GraphRunResult] | None = None


@dataclass(frozen=True)
class GraphEvaluationFinding:
    case_id: str
    passed: bool
    findings: tuple[str, ...]
    transition_count: int
    outcome: str | None
    status: str
    pause_reason: str | None = None
    visited_nodes: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphEvaluationReport:
    cases: tuple[GraphEvaluationFinding, ...]

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)


M3_REQUIRED_SCENARIOS = frozenset(
    {
        "answer",
        "clarify",
        "refuse_identity",
        "refuse_policy",
        "review_pending",
        "review_approved",
        "review_rejected",
        "review_expired",
        "malformed_intent",
        "stale_context",
        "cost_budget",
        "deadline",
        "cycle",
        "cancel",
        "crash_resume",
    }
)

M3_GATE_ORDERS = {
    "answer": (
        "bootstrap",
        "retrieve",
        "extract_intent",
        "resolve",
        "plan",
        "validate",
        "policy",
        "compile",
        "estimate",
        "execute",
        "result_validate",
        "explain",
    ),
    "clarify": ("bootstrap", "retrieve", "extract_intent", "resolve", "clarify"),
    "refuse_identity": ("bootstrap",),
    "refuse_policy": ("bootstrap", "retrieve", "extract_intent", "resolve", "plan", "validate", "policy"),
    "review_pending": ("policy", "compile", "estimate", "approve"),
    "review_approved": ("estimate", "approve", "execute"),
    "review_rejected": ("estimate", "approve"),
    "review_expired": ("estimate", "approve"),
    "malformed_intent": ("bootstrap", "retrieve", "extract_intent"),
    "stale_context": ("bootstrap", "retrieve"),
    "cost_budget": ("policy", "compile", "estimate"),
    "deadline": (),
    "cycle": (),
    "cancel": (),
    "crash_resume": ("bootstrap", "execute", "result_validate", "explain"),
}

M3_FORBIDDEN_NODES = {
    "clarify": frozenset({"compile", "execute"}),
    "refuse_identity": frozenset({"retrieve", "extract_intent", "resolve", "compile", "execute"}),
    "refuse_policy": frozenset({"compile", "execute"}),
    "review_pending": frozenset({"execute"}),
    "review_rejected": frozenset({"execute"}),
    "review_expired": frozenset({"execute"}),
    "malformed_intent": frozenset({"resolve", "compile", "execute"}),
    "stale_context": frozenset({"compile", "execute"}),
    "cost_budget": frozenset({"execute"}),
    "deadline": frozenset({"execute"}),
    "cycle": frozenset({"execute"}),
}


def evaluate_graph_cases(
    runner: AgentGraphRunner,
    cases: tuple[GraphEvaluationCase, ...],
    *,
    owner_id: str = "graph-eval",
    token_prefix: str = "graph-eval",
) -> GraphEvaluationReport:
    findings: list[GraphEvaluationFinding] = []
    for case in cases:
        state = case.build_state()
        result = (
            case.run(runner)
            if case.run
            else runner.start(state, owner_id=owner_id, lease_token=f"{token_prefix}:{case.case_id}")
        )
        problems: list[str] = []
        outcome = result.state.terminal_outcome.kind if result.state.terminal_outcome else None
        if case.expected_outcome is not None and outcome != case.expected_outcome:
            problems.append(f"expected {case.expected_outcome}, received {outcome}")
        if (
            result.state.status == "terminal"
            and result.state.transition_count != len(result.transitions) + state.transition_count
        ):
            problems.append("terminal transition count does not reconcile with emitted trace")
        if result.state.transition_count > result.state.budget.max_transitions:
            problems.append("transition budget was exceeded")
        nodes = [
            node
            for transition in result.transitions
            for node in (transition.from_node, transition.to_node)
            if node is not None
        ]
        cursor = 0
        for required in case.required_gate_order or M3_GATE_ORDERS.get(case.case_id, ()):
            try:
                cursor = nodes.index(required, cursor) + 1
            except ValueError:
                problems.append(f"required gate missing or out of order: {required}")
                break
        forbidden = M3_FORBIDDEN_NODES.get(case.case_id, frozenset())
        violations = forbidden & set(nodes)
        if violations:
            problems.append(f"forbidden gate reached: {', '.join(sorted(violations))}")
        findings.append(
            GraphEvaluationFinding(
                case_id=case.case_id,
                passed=not problems,
                findings=tuple(problems),
                transition_count=len(result.transitions),
                outcome=outcome,
                status=result.state.status,
                pause_reason=(result.state.approval_state or {}).get("reason")
                if isinstance(result.state.approval_state, dict)
                else None,
                visited_nodes=tuple(nodes),
                error_codes=tuple(error.code for error in result.state.errors),
            )
        )
    return GraphEvaluationReport(cases=tuple(findings))


def evaluate_resume_result(case_id: str, result: GraphRunResult, *, max_transitions: int) -> GraphEvaluationFinding:
    problems = []
    if result.state.transition_count > max_transitions:
        problems.append("resumed run exceeded its declared transition budget")
    sequence = [transition.sequence for transition in result.transitions]
    if sequence and sequence != list(range(sequence[0], sequence[0] + len(sequence))):
        problems.append("resumed trace is not contiguous")
    return GraphEvaluationFinding(
        case_id=case_id,
        passed=not problems,
        findings=tuple(problems),
        transition_count=len(result.transitions),
        outcome=result.state.terminal_outcome.kind if result.state.terminal_outcome else None,
        status=result.state.status,
        pause_reason=(result.state.approval_state or {}).get("reason")
        if isinstance(result.state.approval_state, dict)
        else None,
        visited_nodes=tuple(
            node
            for transition in result.transitions
            for node in (transition.from_node, transition.to_node)
            if node is not None
        ),
        error_codes=tuple(error.code for error in result.state.errors),
    )


def validate_m3_coverage(report: GraphEvaluationReport) -> tuple[str, ...]:
    """Return missing cases/outcomes; only a fully populated corpus can pass the M3 gate."""
    by_id = {case.case_id: case for case in report.cases}
    missing_cases = M3_REQUIRED_SCENARIOS - by_id.keys()
    findings = [f"missing scenario: {case_id}" for case_id in sorted(missing_cases)]
    if missing_cases:
        return tuple(findings)
    expected = {
        "answer": "succeeded",
        "clarify": None,
        "refuse_identity": "refused",
        "refuse_policy": "refused",
        "review_pending": None,
        "review_approved": "succeeded",
        "review_rejected": "refused",
        "review_expired": "review_required",
        "malformed_intent": "failed",
        "stale_context": "review_required",
        "cost_budget": "failed",
        "deadline": "failed",
        "cycle": "failed",
        "cancel": "cancelled",
        "crash_resume": "succeeded",
    }
    for case_id, outcome in expected.items():
        if by_id[case_id].outcome != outcome:
            findings.append(f"{case_id}: expected outcome {outcome}, got {by_id[case_id].outcome}")
        if not by_id[case_id].passed:
            findings.extend(f"{case_id}: {finding}" for finding in by_id[case_id].findings)
    required_errors = {
        "refuse_identity": "policy_denied",
        "refuse_policy": "policy_denied",
        "review_expired": "stale_context",
        "malformed_intent": "malformed_model_output",
        "stale_context": "stale_context",
        "cost_budget": "cost_budget_exceeded",
        "deadline": "run_deadline_exceeded",
        "cycle": "cycle_detected",
    }
    for case_id, code in required_errors.items():
        if code not in by_id[case_id].error_codes:
            findings.append(f"{case_id}: required typed error missing: {code}")
    if by_id["review_pending"].status != "waiting_approval":
        findings.append("review_pending: run did not durably pause for approval")
    if by_id["review_pending"].pause_reason != "human_approval":
        findings.append("review_pending: pause reason is not a cost/threshold approval")
    if (
        by_id["clarify"].status != "waiting_approval"
        or by_id["clarify"].pause_reason != "ambiguous_certified_reference"
    ):
        findings.append("clarify: run did not pause with a targeted certified-reference ambiguity")
    for case_id, required in M3_GATE_ORDERS.items():
        nodes = by_id[case_id].visited_nodes
        cursor = 0
        for node in required:
            try:
                cursor = nodes.index(node, cursor) + 1
            except ValueError:
                findings.append(f"{case_id}: required graph gate missing or out of order: {node}")
                break
        violations = M3_FORBIDDEN_NODES.get(case_id, frozenset()) & set(by_id[case_id].visited_nodes)
        if violations:
            findings.append(f"{case_id}: forbidden graph gate reached: {', '.join(sorted(violations))}")
    return tuple(findings)
