"""Production wiring of the governed v2 runtime for the pilot (one API replica).

Builds every node of graph-v2 with real providers: PostgreSQL control store and evidence chain, a read-only PostgreSQL warehouse
gateway, the certified compiler, in-process context from the certified registry, an OpenAI-compatible model behind a bounded retry
and circuit breaker, a deterministic grounded explainer, and the Entra ID verifier. `build_pilot_runtime(settings)` returns a
`V2Runtime` for `app.main`; the same class is used by the tests with injected fakes.

Pilot constraints (documented in infra/terraform/azure-analytics-pilot/README.md): one replica (quota state and the answer-row handoff are
process-local), no OpenSearch, and no prompt rollout pointer in the runtime.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from app.api_v2 import V2Runtime
from app.compiler import PostgreSQLCompilerAdapter
from app.compiler.service import CertifiedIntentCompiler
from app.context.registry_context import (
    CertifiedContracts,
    FixedOntology,
    FixedSnapshots,
    SnapshotSearch,
    context_from_contract,
)
from app.decision_support import ReviewBriefService
from app.execution import (
    ExecutionLimits,
    ExecutionResultStore,
    GatewayCostEstimator,
    GatewayExecutor,
    PostgresGateway,
    run_control_totals,
)
from app.resilience.retry import CircuitBreaker, ResilientGateway, ResilientModelClient
from app.runtime import (
    AgentGraphRunner,
    BootstrapRequest,
    ControlStore,
    EvidenceSealer,
    ExplanationStore,
    ValidationReportStore,
    certified_intent_node,
    clarification_node,
    compile_node,
    context_retrieval_node,
    estimate_node,
    explain_node,
    fake_execution_node,
    governed_graph_v2,
    identity_bootstrap_node,
    ontology_resolution_node,
    policy_node,
    result_validation_node,
    review_decision_node,
    structured_intent_node,
)
from app.runtime.analyze_service import AnswerMaterial, GovernedAnalyzeService
from app.runtime.evidence_store import EvidenceStore
from app.runtime.feedback_service import FeedbackService
from app.runtime.feedback_store import FeedbackStore
from app.runtime.governed_stages import CompiledPlanStore, PolicyValueStore, analytics_plan_node
from app.runtime.run_start import SnapshotSelectionError, new_governed_run_state
from app.runtime.template_explainer import template_explainer
from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.agent_runtime import NodeOutput, RunBudget
from packages.platform_contracts.security import AnalyticsIdentity

DEFAULT_ROLE_MAP = {
    "Analytics.Analyst": (["analytics"], ["analyst"]),
    "Analytics.Reviewer": ([], ["analytics-reviewer"]),
    "Analytics.ReviewAssistant": ([], ["analytics-review-assistant"]),
}


@dataclass
class GovernedRuntime:
    control: ControlStore
    evidence: EvidenceStore
    gateway: Any  # an execution gateway with `dialect`, `estimate`, `execute`
    compiler: Any
    contracts: CertifiedContracts
    contexts: Mapping[str, tuple[Any, Any]]  # analytics tenant -> (context snapshot, ontology snapshot)
    model_factory: Callable[[str], Any]  # request id -> a structured-output client
    explainer: Callable = template_explainer
    review_threshold: float = 5_000.0
    max_cost_units: float = 10_000.0
    run_seconds: int = 120
    min_cohort: int | None = None
    run_id_key: bytes | None = None
    require_run_id_key: bool = False
    plans: CompiledPlanStore = None  # type: ignore[assignment]
    results: ExecutionResultStore = None  # type: ignore[assignment]
    policy_values: PolicyValueStore = None  # type: ignore[assignment]
    explanations: ExplanationStore = field(default_factory=ExplanationStore)
    reports: ValidationReportStore = field(default_factory=ValidationReportStore)
    model_breaker: CircuitBreaker = field(default_factory=lambda: CircuitBreaker("model"))
    warehouse_breaker: CircuitBreaker = field(default_factory=lambda: CircuitBreaker("warehouse"))

    def __post_init__(self) -> None:
        engine = self.control.engine
        self.plans = self.plans or CompiledPlanStore(engine)
        self.results = self.results or ExecutionResultStore(engine)
        self.policy_values = self.policy_values or PolicyValueStore(engine)

    # ---- graph ----

    def _context(self, tenant_id: str):
        try:
            return self.contexts[tenant_id]
        except KeyError as exc:
            raise SnapshotSelectionError("snapshot_tenant_mismatch") from exc

    def nodes(self, identity: AnalyticsIdentity, request: BootstrapRequest) -> dict:
        context, ontology = self._context(identity.tenant_id)
        gateways = {self.gateway.dialect: ResilientGateway(self.gateway, breaker=self.warehouse_breaker)}

        def go(ni, nxt):
            return NodeOutput(run_id=ni.run_id, node_id=ni.node_id, status="completed", next_node=nxt)

        return {
            "create": lambda ni: go(ni, "bootstrap"),
            "bootstrap": identity_bootstrap_node(request),
            "retrieve": context_retrieval_node(FixedSnapshots(context, ontology), SnapshotSearch(context)),
            "extract_intent": structured_intent_node(
                ResilientModelClient(self.model_factory(request.request_id), breaker=self.model_breaker)
            ),
            "resolve": ontology_resolution_node(self.contracts, FixedOntology(ontology)),
            "clarify": clarification_node(),
            "plan": analytics_plan_node(self.contracts),
            "validate": certified_intent_node(self.contracts),
            "policy": policy_node(self.contracts, identity, self.policy_values, review_store=self.control),
            "compile": compile_node(self.compiler, self.plans, self.policy_values),
            "estimate": estimate_node(
                self.plans,
                GatewayCostEstimator(gateways),
                approval_threshold=self.review_threshold,
                review_store=self.control,
                requested_by=identity.user_id,
            ),
            "approve": review_decision_node(self.control),
            "execute": fake_execution_node(
                GatewayExecutor(self.plans, gateways, self.results, ExecutionLimits(), tenant_id=identity.tenant_id)
            ),
            "result_validate": result_validation_node(
                self.plans,
                self.results,
                self.contracts,
                self.control_totals,
                report_sink=lambda ni, report: self.reports.put(ni.tenant_id, ni.run_id, report),
                min_cohort=self.min_cohort,
            ),
            "explain": explain_node(self.results, self.contracts, self.plans, self.explainer, self.explanations),
        }

    def control_totals(self, node_input, intent, contract):
        return run_control_totals(
            intent,
            contract,
            compile_plan=lambda i, c: self.compiler.compile(i),
            gateway=self.gateway,
            limits=ExecutionLimits(),
        )

    def runner(self, identity: AnalyticsIdentity, request: BootstrapRequest) -> AgentGraphRunner:
        return AgentGraphRunner(self.control, governed_graph_v2(self.nodes(identity, request)))

    def new_state(self, request: BootstrapRequest, run_id: str, purpose: str):
        context, _ = self._context(request.identity.tenant_id)
        budget = RunBudget(
            deadline=datetime.now(timezone.utc) + timedelta(seconds=self.run_seconds),
            max_transitions=40,
            max_cost_units=self.max_cost_units,
            max_context_tokens=2_000,
        )
        return new_governed_run_state(
            FixedSnapshots(context, None), request, run_id=run_id, purpose=purpose, budget=budget
        )

    def answer_for(self, state):
        try:
            return AnswerMaterial(
                self.results.get(state.tenant_id, state.run_id, state.execution_reference),
                self.explanations.get(state.tenant_id, state.run_id),
            )
        except LookupError:
            return None

    def service(self) -> GovernedAnalyzeService:
        return GovernedAnalyzeService(
            self.control,
            runner_factory=self.runner,
            state_factory=self.new_state,
            answers=self,
            sealer=EvidenceSealer(self.control, self.evidence, self.reports),
            run_id_key=self.run_id_key,
            require_run_id_key=self.require_run_id_key,
        )

    def feedback_service(self) -> FeedbackService:
        return FeedbackService(self.control, self.evidence, FeedbackStore(self.control.engine), self.contracts)


def _contract_documents(registry_path: str, wanted: list[str]):
    registry = SemanticRegistry(registry_path)
    documents = []
    for item in wanted:
        contract_id, _, version = item.partition("@")
        documents.append(registry.get_certified(contract_id.strip(), version.strip()))
    return documents


def migrate(database_url: str, service_root: Path | None = None) -> None:
    from alembic import command
    from alembic.config import Config

    root = service_root or Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    import os

    previous = os.environ.get("ANALYTICS_CONTROL_DB_URL")
    os.environ["ANALYTICS_CONTROL_DB_URL"] = database_url
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("ANALYTICS_CONTROL_DB_URL", None)
        else:
            os.environ["ANALYTICS_CONTROL_DB_URL"] = previous


def build_pilot_runtime(
    settings: Any, *, model_factory: Callable[[str], Any] | None = None, verifier: Any = None
) -> V2Runtime:
    """Everything is read from settings; `model_factory` and `verifier` can be injected (tests)."""
    if not settings.ANALYTICS_CONTROL_DB_URL or not settings.ANALYTICS_DB_URL:
        raise RuntimeError("ANALYTICS_CONTROL_DB_URL and ANALYTICS_DB_URL are required for the governed runtime")
    if settings.ANALYTICS_MIGRATE_ON_START:
        migrate(settings.ANALYTICS_CONTROL_DB_URL)
    control_engine = create_engine(settings.ANALYTICS_CONTROL_DB_URL, pool_pre_ping=True)
    documents = _contract_documents(
        settings.ANALYTICS_SEMANTIC_REGISTRY_PATH, [c for c in settings.ANALYTICS_V2_CONTRACTS.split(",") if c.strip()]
    )
    if not documents:
        raise RuntimeError("ANALYTICS_V2_CONTRACTS must name at least one certified contract (id@version)")
    contexts = {}
    for document in documents:
        if document.contract.tenant_id in contexts:
            raise RuntimeError("the pilot wiring serves one certified contract per analytics tenant")
        contexts[document.contract.tenant_id] = context_from_contract(document)
    tables = sorted({d.physical_name for doc in documents for d in doc.contract.datasets})
    warehouse = PostgresGateway(create_engine(settings.ANALYTICS_DB_URL, pool_pre_ping=True), allowed_tables=tables)
    if model_factory is None:
        from app.llm_structured import OpenAIStructuredClient

        if settings.AZURE_OPENAI_ENDPOINT:
            client = OpenAIStructuredClient.azure(
                endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY or "",
                api_version=settings.AZURE_OPENAI_API_VERSION,
                deployment=settings.AZURE_OPENAI_DEPLOYMENT,
            )
        else:
            client = OpenAIStructuredClient.openai_compatible(
                api_key=settings.ANALYTICS_LLM_API_KEY or settings.OPENAI_API_KEY or "",
                model=settings.ANALYTICS_LLM_MODEL,
                base_url=settings.ANALYTICS_LLM_BASE_URL,
            )
        model_factory = lambda _request_id: client  # noqa: E731
    if verifier is None:
        from app.security.entra import EntraVerifier

        tenant = settings.ENTRA_TENANT_ID
        verifier = EntraVerifier(
            issuer=f"https://login.microsoftonline.com/{tenant}/v2.0",
            audience=settings.ENTRA_AUDIENCE,
            jwks_url=f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
            tenant_map=json.loads(settings.ANALYTICS_TENANT_MAP),
            role_map={
                k: (list(v[0]), list(v[1]))
                for k, v in (
                    json.loads(settings.ANALYTICS_ROLE_MAP) if settings.ANALYTICS_ROLE_MAP else DEFAULT_ROLE_MAP
                ).items()
            },
        )
    runtime = GovernedRuntime(
        control=ControlStore(control_engine, lease_seconds=settings.ANALYTICS_LEASE_SECONDS),
        evidence=EvidenceStore(control_engine),
        gateway=warehouse,
        compiler=CertifiedIntentCompiler(
            settings.ANALYTICS_SEMANTIC_REGISTRY_PATH,
            PostgreSQLCompilerAdapter(min_cohort=settings.ANALYTICS_MIN_COHORT),
        ),
        contracts=CertifiedContracts(documents),
        contexts=contexts,
        model_factory=model_factory,
        review_threshold=settings.ANALYTICS_REVIEW_COST_THRESHOLD,
        max_cost_units=settings.ANALYTICS_RUN_MAX_COST_UNITS,
        min_cohort=settings.ANALYTICS_MIN_COHORT,
        run_id_key=settings.ANALYTICS_RUN_ID_KEY.encode() if settings.ANALYTICS_RUN_ID_KEY else None,
        require_run_id_key=settings.ENV != "dev",
    )
    started = time.monotonic()
    service = runtime.service()
    v2 = V2Runtime(
        service=service,
        verifier=verifier,
        feedback=runtime.feedback_service(),
        briefs=ReviewBriefService(runtime.control, runtime.plans),
    )
    v2.governed = runtime  # type: ignore[attr-defined]  # kept for the purge job and diagnostics
    v2.started_seconds = time.monotonic() - started  # type: ignore[attr-defined]
    return v2
