"""ADS-078: second-tenant and Apache Ossie portability onboarding drill (fakes only).

A second tenant brings a semantic model in the pinned Apache Ossie format. The drill imports it, shows that the import is a DRAFT that
cannot be served or compiled, then (in a sandbox copy of the registry only) applies the human-authored steps an owner would do
(certify the lifecycle and metric) and compiles and runs a question against the tenant's own data, comparing with an independent oracle.
It also checks isolation between the two tenants' contracts, a lossless export/import round trip, that unsupported or hostile
expressions never become metrics, and that nothing under `app/` or `packages/platform_contracts/` (code, contract schemas) or the
repository registry changed. The sandbox "certification" is a drill transformation in a temp directory: it is NOT a certification, and
the repository registry is never written. Thresholds are PROPOSED until the user approves them.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import duckdb

from app.compiler.adapter import DuckDBCompilerAdapter
from app.compiler.service import CertifiedIntentCompiler
from app.execution import DuckDBGateway, ExecutionLimits
from app.runtime.certification_node import certified_intent_node
from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.agent_runtime import NodeInput, RunBudget
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.ossie import export_ossie, import_ossie
from packages.platform_contracts.semantic import SemanticContract
from reference_stack import m7_corpus as corpus_module
from reference_stack.stack import SERVICE_ROOT, build_stack

HERE = Path(__file__).parent / "m7"
THRESHOLDS = HERE / "onboarding-thresholds.proposed.json"
REPO_ROOT = SERVICE_ROOT.parent.parent
_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
GATE_PLAN = {
    "code_and_schema_changes": "Onboards without product-code or contract-schema changes: 0 changed files",
    "draft_import_served": "An imported (draft) model served or compiled before certification: 0",
    "second_tenant_result_equivalence": "The second tenant's answer equals the independent oracle: 100%",
    "cross_tenant_contract_use": "A tenant using another tenant's contract: 0",
    "round_trip_id_stability": "Export then import keeps dataset ids: 100%",
    "round_trip_omissions": "Metrics and time dimensions lost by an export then import: 0",
    "hostile_expressions_imported": "Unsupported or hostile Ossie expressions that become metrics: 0",
    "first_tenant_unchanged": "The first tenant's answers are unchanged after onboarding: 100%",
}
OSSIE_MODEL = {
    "version": "0.2.0.dev0",
    "semantic_model": [
        {
            "name": "subscriptions",
            "owner": {"id": "team.billing"},
            "datasets": [
                {
                    "name": "subs",
                    "source": "warehouse.subs",
                    "description": "One row per subscription invoice",
                    "primary_key": ["invoice_id"],
                    "fields": [
                        {"name": "invoice_id", "data_type": "string"},
                        {"name": "billed_at", "data_type": "timestamp", "dimension": {"is_time": True}},
                        {"name": "amount", "data_type": "decimal"},
                    ],
                }
            ],
            "metrics": [{"name": "mrr", "dataset": "subs", "expression": "SUM(amount)"}],
        }
    ],
}
TENANT_B = "tenant-b"


def _tree_digest(*roots: Path, suffixes=(".py", ".json")) -> str:
    digest = hashlib.sha256()
    for root in roots:
        for path in sorted(root.rglob("*")):
            if (
                path.is_file()
                and path.suffix in suffixes
                and "tests" not in path.parts
                and "__pycache__" not in path.parts
            ):
                digest.update(str(path.relative_to(REPO_ROOT)).encode() + path.read_bytes())
    return digest.hexdigest()


def _schema_digest() -> str:
    schemas = [SemanticContract.model_json_schema(), AnalyticalIntent.model_json_schema()]
    return hashlib.sha256(json.dumps(schemas, sort_keys=True).encode()).hexdigest()


def _source_digest() -> str:
    return _tree_digest(
        SERVICE_ROOT / "app", REPO_ROOT / "packages" / "platform_contracts", SERVICE_ROOT / "semantic_registry"
    )


def _seed_subs(directory: Path) -> tuple[Path, list[list[str]]]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "subs.parquet"
    connection = duckdb.connect()
    try:
        connection.execute(
            "CREATE TABLE subs AS SELECT 'inv-' || i AS invoice_id, TIMESTAMP '2025-01-01' + INTERVAL (i * 24) HOUR AS billed_at, "
            "CAST(i * 10 AS DECIMAL(12,2)) AS amount FROM range(1, 61) t(i)"
        )
        connection.execute(f"COPY subs TO '{path}' (FORMAT PARQUET)")
    finally:
        connection.close()
    months: dict[str, int] = {}
    from datetime import datetime, timedelta

    for i in range(1, 61):
        key = (datetime(2025, 1, 1) + timedelta(hours=24 * i)).strftime("%Y-%m-01")
        months[key] = months.get(key, 0) + i * 10
    oracle = sorted(([k, str(v)] for k, v in months.items()), key=lambda kv: -int(kv[1]))
    return path, oracle


def _intent(tenant: str, contract_id: str, version: str, dataset: str, metric: str, dimension: str) -> AnalyticalIntent:
    return AnalyticalIntent.model_validate(
        {
            "query_id": f"drill-{tenant}",
            "tenant_id": tenant,
            "dataset_id": dataset,
            "semantic_contract": {"contract_id": contract_id, "contract_version": version},
            "metrics": [{"metric_id": metric}],
            "group_by": [{"dimension_id": dimension, "time_granularity": "month"}],
            "time_range": {"dimension_id": dimension, "start": "2025-01-01T00:00:00Z", "end": "2025-03-31T23:59:59Z"},
            "sort": [{"target_kind": "metric", "target_id": metric, "direction": "desc"}],
            "limit": 25,
        }
    )


def _node_input(tenant: str, intent: AnalyticalIntent) -> NodeInput:
    from datetime import datetime, timedelta, timezone

    return NodeInput(
        run_id="drill-run",
        tenant_id=tenant,
        purpose="analytics",
        request_id=intent.query_id,
        node_id="validate",
        state_version=1,
        context_snapshot_id="snap-drill",
        payload={"intent": intent.model_dump(mode="json")},
        remaining_budget=RunBudget(
            deadline=datetime.now(timezone.utc) + timedelta(minutes=5),
            max_transitions=40,
            max_cost_units=1000.0,
            max_context_tokens=2000,
        ),
    )


def run_onboarding(*, thresholds: dict[str, Any] | None = None, root: Path | None = None) -> dict[str, Any]:
    thresholds = thresholds or json.loads(THRESHOLDS.read_text())
    root = root or Path(tempfile.mkdtemp(prefix="analytics-onboarding-"))
    before = (_source_digest(), _schema_digest())
    steps: list[dict[str, Any]] = []

    def step(name: str, ok: bool, detail: str = "") -> bool:
        steps.append({"step": name, "ok": ok, "detail": detail})
        return ok

    # 1. import: a draft, with a compatibility report that says it is not certification-eligible
    document, report = import_ossie(OSSIE_MODEL, tenant_id=TENANT_B, source_reference="drill://subscriptions")
    step(
        "import is a draft",
        document.lifecycle == "draft" and not report.certification_eligible,
        f"round_trip={report.round_trip}",
    )
    registry_root = root / "registry"
    registry_root.mkdir(parents=True)
    # the sandbox registry carries the first tenant's real contract so isolation can be checked
    first = SemanticRegistry(SERVICE_ROOT / "semantic_registry").get("sales-core", "v1")
    (registry_root / "sales-core-v1.json").write_text(first.model_dump_json(indent=1))
    contract_id, version = document.contract.id, document.contract.version
    (registry_root / "subscriptions-draft.json").write_text(document.model_dump_json(indent=1))
    sandbox = SemanticRegistry(registry_root)

    # 2. a draft is neither served nor compiled
    draft_served = 0
    try:
        sandbox.get_certified(contract_id, version)
        draft_served += 1
    except LookupError:
        pass
    intent = _intent(TENANT_B, contract_id, version, "subs", "mrr", "dimension.subs.billed_at")
    try:
        CertifiedIntentCompiler(registry_root, DuckDBCompilerAdapter()).compile(intent)
        draft_served += 1
    except LookupError:
        pass
    step("draft is refused by the registry and the compiler", draft_served == 0)

    # 3. sandbox only: apply what a human owner would do, in a temp copy (NOT a certification)
    certified = document.model_copy(
        update={
            "lifecycle": "certified",
            "contract": document.contract.model_copy(
                update={
                    "metrics": [m.model_copy(update={"certification": "certified"}) for m in document.contract.metrics]
                }
            ),
        }
    )
    (registry_root / "subscriptions-draft.json").unlink()
    (registry_root / "subscriptions-v1.json").write_text(certified.model_dump_json(indent=1))
    parquet, oracle = _seed_subs(root / "data")
    compiled = CertifiedIntentCompiler(registry_root, DuckDBCompilerAdapter()).compile(intent)
    gateway = DuckDBGateway({"subs": parquet}, allowed_root=root / "data")
    result = gateway.execute(compiled, limits=ExecutionLimits())
    rows = [
        [
            str(c.date().isoformat()) if hasattr(c, "date") else (c.isoformat() if hasattr(c, "isoformat") else str(c))
            for c in row[:1]
        ]
        + [str(int(row[1]))]
        for row in result.rows
    ]
    equivalent = rows == oracle
    step("the second tenant's answer equals the oracle", equivalent, f"got {rows}, wanted {oracle}")

    # 4. isolation between the two tenants' contracts
    cross = 0
    sandbox_cert = certified_intent_node(sandbox)
    for tenant, other_intent in (
        ("tenant-a", _intent("tenant-a", contract_id, version, "subs", "mrr", "dimension.subs.billed_at")),
        (TENANT_B, _intent(TENANT_B, "sales-core", "v1", "orders", "revenue", "created_at")),
    ):
        out = sandbox_cert(_node_input(tenant, other_intent))
        cross += out.status == "completed"
    own = sandbox_cert(_node_input(TENANT_B, intent))
    step("each tenant can use only its own contract", cross == 0 and own.status == "completed", f"own={own.status}")

    # 5. portability: export then import keeps ids
    exported, _ = export_ossie(certified)
    again, _ = import_ossie(exported, tenant_id=TENANT_B, source_reference="drill://roundtrip")
    stable = sorted(x.id for x in again.contract.datasets) == sorted(x.id for x in document.contract.datasets)
    dropped = sorted(
        ({m.id for m in document.contract.metrics} - {m.id for m in again.contract.metrics})
        | {d.id for d in document.contract.dimensions} - {d.id for d in again.contract.dimensions}
    )
    step("export then import keeps dataset ids", stable, f"export omits (by the ADS-008 subset): {dropped}")

    # 6. hostile or unsupported expressions never become metrics
    hostile = json.loads(json.dumps(OSSIE_MODEL))
    hostile["semantic_model"][0]["metrics"] += [
        {"name": "ratio", "dataset": "subs", "expression": "SUM(amount)/COUNT(invoice_id)"},
        {"name": "injected", "dataset": "subs", "expression": "SUM(amount); DROP TABLE subs"},
        {"name": "subquery", "dataset": "subs", "expression": "(SELECT MAX(amount) FROM secrets)"},
        {"name": "unknown_dataset", "dataset": "nope", "expression": "SUM(amount)"},
    ]
    hostile_doc, hostile_report = import_ossie(hostile, tenant_id=TENANT_B, source_reference="drill://hostile")
    imported = {m.id for m in hostile_doc.contract.metrics}
    leaked = len(imported - {"mrr"})
    step(
        "unsupported and hostile expressions are reported lossy and dropped",
        leaked == 0 and hostile_report.round_trip == "lossy",
        f"metrics={sorted(imported)}",
    )

    # 7. the first tenant is unchanged
    stack = build_stack("duckdb", root / "first")
    who = stack.verifier().verify(stack.token("requester"))
    answer = stack.service().analyze(
        who, purpose="analytics", idempotency_key="onboard-first-001", request_text="Show monthly revenue"
    )
    first_ok = [list(r) for r in answer.outcome.result.rows] == corpus_module.expected("monthly_paid")[1]
    step("the first tenant still gets the oracle answer", first_ok)

    after = (_source_digest(), _schema_digest())
    changed = sum(a != b for a, b in zip(before, after, strict=True))
    metrics = {
        "code_and_schema_changes": changed,
        "draft_import_served": draft_served,
        "second_tenant_result_equivalence": 1.0 if equivalent else 0.0,
        "cross_tenant_contract_use": cross,
        "round_trip_id_stability": 1.0 if stable else 0.0,
        "round_trip_omissions": len(dropped),
        "hostile_expressions_imported": leaked,
        "first_tenant_unchanged": 1.0 if first_ok else 0.0,
    }
    gates = {
        name: {
            "value": metrics[name],
            "op": gate["op"],
            "threshold": gate["value"],
            "meets": bool(_OPS[gate["op"]](metrics[name], gate["value"])),
        }
        for name, gate in thresholds["gates"].items()
    }
    return {
        "packet": "ADS-078",
        "approval": thresholds["approval"],
        "ok": all(g["meets"] for g in gates.values()),
        "gates": gates,
        "gate_plan": GATE_PLAN,
        "ossie_report": report.model_dump(mode="json"),
        "manual_steps": thresholds["manual_steps"],
        "not_measured": thresholds["not_measured"],
        "steps": steps,
    }


def render_markdown(report: dict[str, Any]) -> str:
    approval = report["approval"]["status"]
    lines = [
        "# ADS-078: Second-Tenant and Apache Ossie Portability Onboarding Drill",
        "",
        f"**Result: {'MEETS' if report['ok'] else 'DOES NOT MEET'} the {approval} thresholds.** The thresholds are {approval.upper()}{' and NOT APPROVED' if approval != 'approved' else ''}. "
        'The drill\'s "certification" is a transformation of a temp copy of the registry: **it is not a certification**, and the repository registry is never written.',
        "",
        "## Metrics",
        "",
        "| Metric | Measured | Gate | Meets | Plan gate |",
        "|---|---:|---:|:---:|---|",
    ]
    for name, gate in report["gates"].items():
        lines.append(
            f"| `{name}` | {gate['value']:.4g} | {gate['op']} {gate['threshold']} | {'yes' if gate['meets'] else '**NO**'} | {report['gate_plan'][name]} |"
        )
    lines += ["", "## Steps", "", "| Step | OK | Detail |", "|---|:---:|---|"]
    lines += [f"| {s['step']} | {'yes' if s['ok'] else '**NO**'} | {s['detail']} |" for s in report["steps"]]
    lines += ["", "## What a person must still do (not automated, not done here)", ""] + [
        f"- {m}" for m in report["manual_steps"]
    ]
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)
