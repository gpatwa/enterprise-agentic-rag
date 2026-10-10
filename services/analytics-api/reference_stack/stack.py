"""Assemble the governed v2 runtime from local fakes (ADS-048)."""

from __future__ import annotations

import hashlib
import secrets
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from jose import jwt
from sqlalchemy import create_engine

from app.api_v2 import V2Runtime, build_v2_router
from app.compiler import DuckDBCompilerAdapter, PostgreSQLCompilerAdapter
from app.compiler.service import CertifiedIntentCompiler
from app.execution import (
    DuckDBGateway,
    ExecutionLimits,
    ExecutionResultStore,
    GatewayCostEstimator,
    GatewayExecutor,
    PostgresGateway,
    run_control_totals,
)
from app.proposals import ProposalService, ProposalStore
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
from app.runtime.run_start import new_governed_run_state
from app.security import OIDCVerifier
from app.semantic_registry import SemanticRegistry
from app.triage import TriageService, TriageStore
from packages.platform_contracts.agent_runtime import NodeOutput, RunBudget
from packages.platform_contracts.security import AnalyticsIdentity
from packages.platform_contracts.semantic import SemanticPolicy, SemanticRegistryDocument
from reference_stack.fakes import (
    PURPOSE,
    TENANT,
    ContractsProvider,
    EmulatedPostgresEngine,
    OntologyProvider,
    ScriptedIntentClient,
    SearchProvider,
    SnapshotProvider,
    build_context,
    scripted_explainer,
    seed_lake,
)

SERVICE_ROOT = Path(__file__).resolve().parent.parent
Engine = Literal["duckdb", "postgres"]
REFERENCE_MAX_COST_UNITS = 10_000.0
ISSUER, AUDIENCE, KEY_ID = "https://reference.local", "analytics", "reference"


class RecordingGateway:
    """Delegates to a gateway and records the SQL of every executed plan."""

    def __init__(self, inner, log: list) -> None:
        self.inner, self.log, self.dialect = inner, log, inner.dialect

    def estimate(self, plan):
        return self.inner.estimate(plan)

    def execute(self, plan, **kwargs):
        self.log.append(plan.sql)
        return self.inner.execute(plan, **kwargs)


@dataclass
class ReferenceStack:
    engine: Engine
    workdir: Path
    control: ControlStore
    evidence: EvidenceStore
    gateway: object
    compiler: CertifiedIntentCompiler
    contracts: ContractsProvider
    plans: CompiledPlanStore = field(default_factory=CompiledPlanStore)
    results: ExecutionResultStore = field(default_factory=ExecutionResultStore)
    explanations: ExplanationStore = field(default_factory=ExplanationStore)
    reports: ValidationReportStore = field(default_factory=ValidationReportStore)
    policy_values: PolicyValueStore = field(default_factory=PolicyValueStore)
    review_threshold: float = 1e9
    ambiguous: bool = False
    omit_context_ids: tuple = ()
    max_cost_units: float = REFERENCE_MAX_COST_UNITS
    executed_sql: list = field(default_factory=list)
    compiled_sql: set = field(default_factory=set)
    timings: list = field(default_factory=list)  # (node_id, seconds) for policy/compile
    secret: str = field(default_factory=lambda: secrets.token_urlsafe(32))

    # ---- identity (locally signed; never accepted by any other service) ----

    def token(self, user: str, *, purposes=(PURPOSE,), ttl_minutes: int = 60, tenant: str = TENANT) -> str:
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": user,
            "tid": tenant,
            "groups": ["analyst"],
            "purposes": list(purposes),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        }
        return jwt.encode(claims, self.secret, algorithm="HS256", headers={"kid": KEY_ID})

    def verifier(self) -> OIDCVerifier:
        return OIDCVerifier(ISSUER, AUDIENCE, {KEY_ID: self.secret}, algorithms=("HS256",))

    # ---- runtime wiring ----

    def nodes(self, identity: AnalyticsIdentity, request: BootstrapRequest, review_store=None) -> dict:
        store = review_store or self.control
        context, ontology = build_context(self.contracts.document, ambiguous=self.ambiguous, omit=self.omit_context_ids)
        gateways = {self.gateway.dialect: RecordingGateway(self.gateway, self.executed_sql)}

        def go(ni, nxt):
            return NodeOutput(run_id=ni.run_id, node_id=ni.node_id, status="completed", next_node=nxt)

        handlers = {
            "create": lambda ni: go(ni, "bootstrap"),
            "bootstrap": identity_bootstrap_node(request),
            "retrieve": context_retrieval_node(SnapshotProvider(context), SearchProvider()),
            "extract_intent": structured_intent_node(
                ScriptedIntentClient(request.request_id, ambiguous=self.ambiguous)
            ),
            "resolve": ontology_resolution_node(self.contracts, OntologyProvider(ontology)),
            "clarify": clarification_node(),
            "plan": analytics_plan_node(self.contracts),
            "validate": certified_intent_node(self.contracts),
            "policy": policy_node(self.contracts, identity, self.policy_values, review_store=store),
            "compile": compile_node(self.compiler, self.plans, self.policy_values),
            "estimate": estimate_node(
                self.plans,
                GatewayCostEstimator(gateways),
                approval_threshold=self.review_threshold,
                review_store=store,
                requested_by=identity.user_id,
            ),
            "approve": review_decision_node(self.control),
            "execute": fake_execution_node(GatewayExecutor(self.plans, gateways, self.results, ExecutionLimits())),
            "result_validate": result_validation_node(
                self.plans,
                self.results,
                self.contracts,
                self.control_totals,
                report_sink=lambda ni, report: self.reports.put(ni.tenant_id, ni.run_id, report),
            ),
            "explain": explain_node(self.results, self.contracts, self.plans, scripted_explainer, self.explanations),
        }
        for name in ("policy", "compile"):
            handlers[name] = self._timed(name, handlers[name])
        return handlers

    def _timed(self, name, handler):
        def run(node_input):
            started = time.perf_counter()
            try:
                return handler(node_input)
            finally:
                self.timings.append((name, time.perf_counter() - started))

        return run

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
        context, _ = build_context(self.contracts.document, ambiguous=self.ambiguous, omit=self.omit_context_ids)
        # Gateway cost units are per dialect and uncalibrated (see ADS-040); the default budget of
        # 100 units rejects even an unfiltered scan of this 100-row table on DuckDB, so the
        # reference stack states its own budget explicitly.
        budget = RunBudget(
            deadline=datetime.now(timezone.utc) + timedelta(minutes=5),
            max_transitions=40,
            max_cost_units=self.max_cost_units,
            max_context_tokens=2_000,
        )
        return new_governed_run_state(SnapshotProvider(context), request, run_id=run_id, purpose=purpose, budget=budget)

    def answer_for(self, state):
        return AnswerMaterial(
            self.results.get(state.tenant_id, state.run_id, state.execution_reference),
            self.explanations.get(state.tenant_id, state.run_id),
        )

    def service(self) -> GovernedAnalyzeService:
        return GovernedAnalyzeService(
            self.control,
            runner_factory=self.runner,
            state_factory=self.new_state,
            answers=self,
            sealer=EvidenceSealer(self.control, self.evidence, self.reports),
        )

    def proposal_service(self) -> ProposalService:
        engine = self.control.engine
        return ProposalService(
            self.control,
            self.evidence,
            FeedbackStore(engine),
            TriageStore(engine),
            ProposalStore(engine),
            self.contracts,
        )

    def triage_service(self) -> TriageService:
        return TriageService(
            self.control, self.evidence, FeedbackStore(self.control.engine), TriageStore(self.control.engine)
        )

    def feedback_service(self) -> FeedbackService:
        store = FeedbackStore(self.control.engine)
        return FeedbackService(self.control, self.evidence, store, self.contracts)

    def app(self) -> FastAPI:
        """The v2 API with this stack as its runtime. Not used by `app.main`."""
        application = FastAPI(title="Compass Analytics reference stack")

        async def no_api_key() -> None:
            return None

        runtime = V2Runtime(service=self.service(), verifier=self.verifier(), feedback=self.feedback_service())
        application.include_router(build_v2_router(runtime, no_api_key))
        return application


def build_stack(
    engine: Engine,
    workdir: Path | None = None,
    *,
    review_threshold: float = 1e9,
    denied: bool = False,
    ambiguous: bool = False,
    omit_context_ids: tuple = (),
    max_cost_units: float = REFERENCE_MAX_COST_UNITS,
) -> ReferenceStack:
    """Create the seeded data, migrated control store, gateway, and compiler for one dialect."""
    workdir = Path(workdir or tempfile.mkdtemp(prefix="analytics-reference-"))
    parquet = seed_lake(workdir)
    database = f"sqlite:///{workdir / 'control.db'}"
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database)
    _upgrade(config, database)
    sql_engine = create_engine(database)
    if engine == "duckdb":
        gateway = DuckDBGateway({"sales_orders": parquet}, allowed_root=workdir)
        adapter = DuckDBCompilerAdapter()
    else:
        gateway = PostgresGateway(EmulatedPostgresEngine(parquet), allowed_tables=["sales_orders"])
        adapter = PostgreSQLCompilerAdapter()
    document = SemanticRegistry(SERVICE_ROOT / "semantic_registry").get_certified("sales-core", "v1")
    if denied:  # a policy that allows revenue only for a different purpose
        policy = SemanticPolicy(
            id="deny-analytics",
            target_ids=["revenue"],
            classification="internal",
            allowed_purposes=["billing"],
            owner_ids=["team.data"],
        )
        document = SemanticRegistryDocument(
            lifecycle="certified", contract=document.contract.model_copy(update={"policies": [policy]})
        )
    compiler = CertifiedIntentCompiler(SERVICE_ROOT / "semantic_registry", adapter=adapter)
    original = compiler.compile
    compiled_sql: set = set()

    def recording_compile(*args, **kwargs):
        plan = original(*args, **kwargs)
        compiled_sql.add(plan.sql)
        return plan

    compiler.compile = recording_compile
    return ReferenceStack(
        engine=engine,
        workdir=workdir,
        control=ControlStore(sql_engine),
        evidence=EvidenceStore(sql_engine),
        gateway=gateway,
        compiler=compiler,
        contracts=ContractsProvider(document),
        review_threshold=review_threshold,
        ambiguous=ambiguous,
        omit_context_ids=omit_context_ids,
        max_cost_units=max_cost_units,
        compiled_sql=compiled_sql,
    )


def _upgrade(config: Config, database: str) -> None:
    import os

    previous = os.environ.get("ANALYTICS_CONTROL_DB_URL")
    os.environ["ANALYTICS_CONTROL_DB_URL"] = database
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("ANALYTICS_CONTROL_DB_URL")
        else:
            os.environ["ANALYTICS_CONTROL_DB_URL"] = previous


def fingerprint_rows(rows) -> str:
    return hashlib.sha256(repr([[str(cell) for cell in row] for row in rows]).encode()).hexdigest()
