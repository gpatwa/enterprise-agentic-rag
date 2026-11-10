"""Deterministic local stand-ins for the model, search, context, and PostgreSQL server."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb
import sqlglot

from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.context_snapshot import ContextPackItem, ContextSnapshot
from packages.platform_contracts.metadata import MetadataAsset, MetadataColumn
from packages.platform_contracts.ontology import OntologyEdge, OntologyNode, OntologyProvenance, OntologySnapshot
from packages.platform_contracts.semantic import SemanticRegistryDocument

TENANT = "tenant-a"
PURPOSE = "analytics"
SNAPSHOT_ID = "reference-context-v1"
FIXED_TIME = datetime(2026, 10, 1, tzinfo=timezone.utc)
SEED_SQL = """CREATE TABLE sales_orders AS SELECT 'o' || i AS id, CAST(i AS DECIMAL(12,2)) AS amount,
    CASE WHEN i % 5 = 0 THEN 'refunded' ELSE 'paid' END AS status,
    TIMESTAMP '2024-01-01' + INTERVAL (i * 20) HOUR AS created_at FROM range(1, 101) t(i)"""


def seed_lake(directory: Path) -> Path:
    """Write the deterministic `sales_orders` Parquet file (100 orders, Jan-Mar 2024)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sales_orders.parquet"
    connection = duckdb.connect()
    try:
        connection.execute(SEED_SQL)
        connection.execute(f"COPY sales_orders TO '{path}' (FORMAT PARQUET)")
    finally:
        connection.close()
    return path


# ---- model: a scripted, schema-valid intent extractor ----


class ScriptedIntentClient:
    """Maps known questions to certified intents; anything else is malformed output.

    Exact (normalized) questions win; a few keywords are the fallback. A question can also make
    the "model" misbehave (emit raw SQL) so the pipeline's refusal of it can be measured.
    """

    def __init__(self, request_id: str, tenant_id: str = TENANT, *, ambiguous: bool = False) -> None:
        self.request_id, self.tenant_id, self.ambiguous = request_id, tenant_id, ambiguous

    def complete_json(self, *, prompt: str, schema: dict, max_tokens: int) -> dict[str, Any]:
        question = " ".join(re.sub(r"[^a-z ]", " ", prompt.rsplit("Request:", 1)[-1].lower()).split())
        base = {
            "query_id": self.request_id,
            "tenant_id": self.tenant_id,
            "dataset_id": "orders",
            "semantic_contract": {"contract_id": "sales-core", "contract_version": "v1"},
            "metrics": [{"metric_id": "revenue"}],
        }
        desc = [{"target_kind": "metric", "target_id": "revenue", "direction": "desc"}]
        jan_mar = {"dimension_id": "created_at", "start": "2024-01-01T00:00:00Z", "end": "2024-03-31T23:59:59Z"}
        monthly = {
            "group_by": [{"dimension_id": "created_at", "time_granularity": "month"}],
            "time_range": jan_mar,
            "sort": desc,
            "limit": 25,
        }
        paid = [{"field_id": "orders.status", "operator": "equals", "values": ["paid"]}]
        by_status = {"group_by": [{"dimension_id": "status"}], "sort": desc, "limit": 25}
        catalog = {
            "monthly revenue for all statuses": monthly,
            "revenue for refunded orders": {
                **by_status,
                "filters": [{"field_id": "orders.status", "operator": "equals", "values": ["refunded"]}],
            },
            "top revenue status": {**by_status, "limit": 1},
        }
        if question == "model emits sql":
            return {"raw_sql": "DROP TABLE sales_orders"}
        if question in catalog:
            intent = {**base, **catalog[question]}
        elif "status" in question:
            intent = {**base, **by_status}
        elif "month" in question:
            intent = {**base, **monthly, "filters": paid}
        elif "total" in question:
            intent = {**base, "limit": 1}
        else:
            return {"unsupported_request": True}
        if self.ambiguous:  # the "model" names a time dimension by a label the ontology maps to many IDs
            for grouping in intent.get("group_by", []):
                grouping["dimension_id"] = "time"
            if intent.get("time_range"):
                intent["time_range"]["dimension_id"] = "time"
        return AnalyticalIntent.model_validate(intent).model_dump(mode="json")


def scripted_explainer(sheet, violations):
    """Grounded prose from the first row only; cites exactly the cells it quotes."""
    from app.execution import DraftClaim

    first, second = sheet.get("cell:r0c0"), sheet.get("cell:r0c1")
    if first is None:
        raise LookupError("no rows to explain")
    if second is None:
        return [DraftClaim(f"The total is {first.value}.", ("cell:r0c0", "metric:revenue"))]
    return [
        DraftClaim(
            f"The top result is {first.value} with {second.value}.", ("cell:r0c0", "cell:r0c1", "metric:revenue")
        )
    ]


# ---- context, search, ontology, contracts ----


class SnapshotProvider:
    def __init__(self, snapshot: ContextSnapshot) -> None:
        self.snapshot = snapshot

    def get(self, snapshot_id: str, tenant_id: str) -> ContextSnapshot:
        if (snapshot_id, tenant_id) != (self.snapshot.snapshot_id, self.snapshot.tenant_id):
            raise LookupError("context snapshot scope mismatch")
        return self.snapshot

    def current_snapshot(self) -> ContextSnapshot:
        return self.snapshot


class SearchProvider:
    """Returns the certified dataset; metrics and dimensions reach the pack through graph closure."""

    def search(self, query: str, *, tenant_id: str, snapshot_id: str, certified_only=True, limit=10):
        return (
            ContextPackItem(
                asset_id="orders",
                score=1.0,
                text="Certified sales orders dataset with revenue and order dates.",
                citation=f"context:{snapshot_id}:orders",
                certified=True,
            ),
        )


class OntologyProvider:
    def __init__(self, snapshot: OntologySnapshot) -> None:
        self.snapshot = snapshot

    def get(self, snapshot_id: str, tenant_id: str) -> OntologySnapshot:
        if (snapshot_id, tenant_id) != (self.snapshot.snapshot_id, self.snapshot.tenant_id):
            raise LookupError("ontology snapshot scope mismatch")
        return self.snapshot


class ContractsProvider:
    def __init__(self, document: SemanticRegistryDocument) -> None:
        self.document = document

    def get_certified(self, contract_id: str, version: str) -> SemanticRegistryDocument:
        if (contract_id, version) != (self.document.contract.id, self.document.contract.version):
            raise LookupError("exact certified contract not found")
        if self.document.lifecycle != "certified":
            raise LookupError("contract is not certified")
        return self.document


def build_context(
    document: SemanticRegistryDocument, *, ambiguous: bool = False, omit: tuple[str, ...] = ()
) -> tuple[ContextSnapshot, OntologySnapshot]:
    """Context and ontology snapshots derived from the certified contract (nothing is promoted)."""
    contract = document.contract
    provenance = OntologyProvenance(
        source_system="reference-stack",
        source_id="sales-core-v1",
        source_version="v1",
        observed_at=FIXED_TIME,
        fingerprint="a" * 64,
    )
    kinds = (
        (contract.datasets, "dataset"),
        (contract.metrics, "metric"),
        (contract.dimensions, "dimension"),
        (contract.fields, "field"),
    )
    nodes = [
        OntologyNode(
            node_id=asset.id,
            tenant_id=contract.tenant_id,
            node_type=kind,
            label="time" if ambiguous and kind == "dimension" else asset.id,
            lifecycle="certified",
            valid_from=FIXED_TIME - timedelta(days=1),
            provenance=(provenance.model_copy(update={"source_id": asset.id}),),
        )
        for assets, kind in kinds
        for asset in assets
    ]
    # The dataset "contains" its metrics and dimensions, so graph closure puts them in the context
    # pack; ids in `omit` get no edge, which simulates a retrieval miss.
    edges = tuple(
        OntologyEdge(
            edge_id=f"{dataset.id}-contains-{asset.id}",
            tenant_id=contract.tenant_id,
            edge_type="contains",
            from_node_id=dataset.id,
            to_node_id=asset.id,
            valid_from=FIXED_TIME - timedelta(days=1),
            provenance=(provenance.model_copy(update={"source_id": f"{dataset.id}-{asset.id}"}),),
        )
        for dataset in contract.datasets
        for asset in (*contract.metrics, *contract.dimensions)
        if asset.dataset_id == dataset.id and asset.id not in omit
    )
    ontology = OntologySnapshot(
        snapshot_id=SNAPSHOT_ID, tenant_id=contract.tenant_id, captured_at=FIXED_TIME, nodes=tuple(nodes), edges=edges
    )
    datasets = tuple(
        MetadataAsset(
            id=dataset.id,
            display_name=dataset.display_name,
            physical_name=dataset.physical_name,
            provider="semantic-registry",
            description=dataset.description,
            owner_ids=dataset.owner_ids,
            certified=True,
            source_version=f"{contract.id}@{contract.version}",
            observed_at=FIXED_TIME,
            columns=[
                MetadataColumn(name=f.physical_name, data_type=f.data_type, classification=f.classification)
                for f in contract.fields
                if f.dataset_id == dataset.id
            ],
        )
        for dataset in contract.datasets
    )
    context = ContextSnapshot.build(
        snapshot_id=SNAPSHOT_ID,
        tenant_id=contract.tenant_id,
        source_fingerprints=("b" * 64,),
        metadata_assets=datasets,
        ontology=ontology,
        semantic_contract_ids=(f"{contract.id}@{contract.version}",),
        created_at=FIXED_TIME,
    )
    return context, ontology


# ---- an emulated PostgreSQL server (no network, no server) ----

_COST = 25.0


class _Result:
    def __init__(self, columns: list[str], rows: list[tuple]) -> None:
        self._columns, self._rows = columns, rows

    def keys(self):
        return self._columns

    def fetchmany(self, size: int):
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch

    def fetchone(self):
        return self._rows[0]

    def close(self) -> None:
        pass


class _Connection:
    def __init__(self, engine: "EmulatedPostgresEngine") -> None:
        self.engine = engine
        self.connection = SimpleNamespace(driver_connection=SimpleNamespace(cancel=lambda: None))

    def exec_driver_sql(self, statement: str) -> None:
        self.engine.session_statements.append(statement)

    def execution_options(self, **_options):
        return self

    def execute(self, clause, parameters=None):
        sql = str(clause)
        if sql.startswith("EXPLAIN (FORMAT JSON)"):
            return _Result(["QUERY PLAN"], [([{"Plan": {"Total Cost": _COST}}],)])
        self.engine.executed_sql.append(sql)
        return self.engine.run(sql, dict(parameters or {}))

    def rollback(self) -> None:
        self.engine.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class EmulatedPostgresEngine:
    """Stands in for a SQLAlchemy engine on a read-only PostgreSQL role.

    Postgres-dialect SQL is transpiled to DuckDB and run over the seeded Parquet file, so the
    journey returns real, comparable rows. Session statements and the EXPLAIN probe are
    recorded and answered; cost is a fixed deterministic value.
    """

    def __init__(self, parquet: Path) -> None:
        self.parquet = Path(parquet)
        self.session_statements: list[str] = []
        self.executed_sql: list[str] = []
        self.rollbacks = 0

    def connect(self) -> _Connection:
        return _Connection(self)

    def run(self, sql: str, parameters: dict[str, Any]) -> _Result:
        translated = sqlglot.transpile(sql, read="postgres", write="duckdb")[0]
        connection = duckdb.connect()
        try:
            connection.execute("SET TimeZone='UTC'")
            connection.execute(f"CREATE VIEW sales_orders AS SELECT * FROM read_parquet('{self.parquet.as_posix()}')")
            cursor = connection.execute(translated, parameters)
            columns = [item[0] for item in cursor.description]
            return _Result(columns, cursor.fetchall())
        finally:
            connection.close()
