"""ADS-044: incremental refresh, tombstones, source failure, and stale-snapshot behavior."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.context import (
    ContextRefreshWorker,
    ContextSnapshotRegistry,
    DbtArtifactRefreshSource,
    NoSnapshotError,
    ProviderRefreshSource,
    RefreshStateStore,
    StalenessPolicy,
    StaleSnapshotError,
)
from app.context.snapshot_registry import ContextSnapshotNotFoundError
from app.metadata.providers import DbtManifestProvider, OpenMetadataProvider

START = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def _model(name, description="d", checksum="c1"):
    return {
        "resource_type": "model",
        "name": name,
        "alias": name,
        "description": description,
        "columns": {"id": {"description": "key"}},
        "checksum": {"checksum": checksum},
        "depends_on": {"nodes": []},
        "meta": {"certified": True, "owner": "team.data"},
        "tags": [],
    }


class Warehouse:
    """Mutable fake sources so each test can drive a refresh cycle."""

    def __init__(self):
        self.dbt_models = {"orders": _model("orders"), "customers": _model("customers")}
        self.om_tables = {
            "payments": {
                "fullyQualifiedName": "wh.payments",
                "description": "p1",
                "columns": [{"name": "id", "dataType": "INT"}],
            }
        }
        self.om_fail = False
        self.om_empty = False

    def manifest(self):
        return {"nodes": {f"model.shop.{name}": node for name, node in self.dbt_models.items()}}

    def dbt_source(self):
        provider = DbtManifestProvider(self.manifest())
        source = ProviderRefreshSource(provider, ["orders", "customers"], name="dbt")
        source.provider = _LiveDbt(self)
        return source

    def om_source(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if self.om_fail:
                return httpx.Response(500)
            if self.om_empty:
                return httpx.Response(404)
            name = request.url.path.rsplit("/", 1)[-1]
            table = self.om_tables.get(name)
            return httpx.Response(200, json=table) if table else httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = OpenMetadataProvider("http://om.local", "token", client)
        return ProviderRefreshSource(provider, ["payments"], name="openmetadata")


class _LiveDbt:
    provider_name = "dbt"

    def __init__(self, warehouse):
        self.warehouse = warehouse

    def get_snapshot(self, name):
        return DbtManifestProvider(self.warehouse.manifest()).get_snapshot(name)


@pytest.fixture
def env(tmp_path):
    warehouse, clock = Warehouse(), Clock()
    registry = ContextSnapshotRegistry(tmp_path / "snapshots")
    published = []

    def worker(**overrides):
        arguments = dict(
            tenant_id="tenant-a",
            sources=[warehouse.dbt_source(), warehouse.om_source()],
            registry=registry,
            state=RefreshStateStore(tmp_path / "state"),
            clock=clock,
            semantic_contract_ids=("commerce@v1",),
            on_publish=published.append,
        )
        arguments.update(overrides)
        return ContextRefreshWorker(**arguments)

    return warehouse, clock, registry, published, worker


def _ids(snapshot):
    return sorted(asset.id for asset in snapshot.metadata_assets)


def test_first_run_publishes_merged_snapshot_with_full_provenance(env):
    warehouse, clock, registry, published, make = env
    worker = make()
    report = worker.run_once()
    assert report.status == "published" and report.sources["dbt"].added == ("model.shop.customers", "model.shop.orders")
    snapshot = worker.current_snapshot()
    assert _ids(snapshot) == ["model.shop.customers", "model.shop.orders", "wh.payments"]
    assert all(asset.source_version for asset in snapshot.metadata_assets)
    assert snapshot.semantic_contract_ids == ("commerce@v1",) and published == [snapshot]
    with pytest.raises(ContextSnapshotNotFoundError):
        registry.get(snapshot.snapshot_id, "tenant-b")


def test_unchanged_sources_do_not_publish_new_snapshot_but_renew_verification(env):
    warehouse, clock, registry, published, make = env
    worker = make()
    first = worker.run_once()
    clock.advance(hours=20)
    second = worker.run_once()
    assert second.status == "unchanged" and second.snapshot_id == first.snapshot_id and len(published) == 1
    clock.advance(hours=20)  # 40h since publish, 20h since last successful verification
    assert worker.current_snapshot().snapshot_id == first.snapshot_id


def test_incremental_refresh_reports_only_changed_assets_and_keeps_old_snapshot_immutable(env):
    warehouse, clock, registry, published, make = env
    worker = make()
    first = worker.run_once()
    warehouse.om_tables["payments"]["description"] = "p2"
    clock.advance(minutes=30)
    second = worker.run_once()
    assert second.status == "published" and second.snapshot_id != first.snapshot_id
    assert second.sources["openmetadata"].updated == ("wh.payments",)
    assert second.sources["dbt"].added == second.sources["dbt"].updated == second.sources["dbt"].removed == ()
    assert (
        registry.get(first.snapshot_id, "tenant-a").content_fingerprint
        != registry.get(second.snapshot_id, "tenant-a").content_fingerprint
    )
    old = {a.id: a.description for a in registry.get(first.snapshot_id, "tenant-a").metadata_assets}
    assert old["wh.payments"] == "p1"


def test_removed_assets_are_tombstoned_and_reappearance_lifts_the_tombstone(env):
    warehouse, clock, registry, published, make = env
    worker = make()
    worker.run_once()
    del warehouse.dbt_models["customers"]
    del warehouse.om_tables["payments"]
    clock.advance(hours=1)
    report = worker.run_once()
    # OpenMetadata is now empty after being populated: an outage signature, so payments is kept.
    assert report.sources["dbt"].removed == ("model.shop.customers",)
    assert report.sources["openmetadata"].status == "failed"
    assert _ids(worker.current_snapshot()) == ["model.shop.orders", "wh.payments"]
    warehouse.dbt_models["customers"] = _model("customers", checksum="c2")
    clock.advance(hours=1)
    worker.run_once()
    assert "model.shop.customers" in _ids(worker.current_snapshot())


def test_single_removed_asset_from_healthy_source_is_tombstoned(env):
    warehouse, clock, registry, published, make = env
    warehouse.om_tables["ledger"] = {"fullyQualifiedName": "wh.ledger", "columns": [{"name": "id", "dataType": "INT"}]}
    om = warehouse.om_source()
    om.asset_names = ("payments", "ledger")
    worker = make(sources=[warehouse.dbt_source(), om])
    worker.run_once()
    del warehouse.om_tables["ledger"]
    clock.advance(hours=1)
    report = worker.run_once()
    assert report.status == "published" and report.tombstoned_asset_ids == ("wh.ledger",)
    assert report.sources["openmetadata"].removed == ("wh.ledger",)
    assert "wh.ledger" not in _ids(worker.current_snapshot())


def test_failing_source_keeps_last_good_data_and_does_not_renew_verification(env):
    warehouse, clock, registry, published, make = env
    worker = make()
    worker.run_once()
    warehouse.om_fail = True
    warehouse.dbt_models["orders"] = _model("orders", description="new", checksum="c2")
    clock.advance(hours=1)
    report = worker.run_once()
    assert report.status == "published"
    assert report.sources["openmetadata"].status == "failed" and "HTTP 500" in report.sources["openmetadata"].error
    snapshot = worker.current_snapshot()
    assert "wh.payments" in _ids(snapshot)
    assert {a.id: a.description for a in snapshot.metadata_assets}["model.shop.orders"] == "new"
    assert "token" not in report.sources["openmetadata"].error


def test_failure_with_no_prior_data_publishes_remaining_sources_or_fails(env):
    warehouse, clock, registry, published, make = env
    warehouse.om_fail = True
    worker = make()
    assert worker.run_once().status == "published"
    assert _ids(worker.current_snapshot()) == ["model.shop.customers", "model.shop.orders"]

    class Broken:
        name = "broken"

        def fetch(self):
            raise RuntimeError("connection reset by https://secret.example/?token=abc")

    only = make(sources=[Broken()], tenant_id="tenant-z")
    report = only.run_once()
    assert report.status == "failed" and report.sources["broken"].error == "RuntimeError"
    with pytest.raises(NoSnapshotError):
        only.current_snapshot()


def test_stale_source_blocks_publication_and_snapshot_reads_fail_closed(env):
    warehouse, clock, registry, published, make = env
    worker = make(policy=StalenessPolicy(max_source_age=timedelta(hours=2), max_snapshot_age=timedelta(hours=5)))
    first = worker.run_once()
    warehouse.om_fail = True
    warehouse.dbt_models["orders"] = _model("orders", description="changed", checksum="c2")
    clock.advance(hours=3)
    report = worker.run_once()
    assert report.status == "blocked" and "stale metadata" in report.blocking_reasons
    assert report.sources["openmetadata"].status == "reused_stale"
    assert len(published) == 1  # nothing newer was published
    assert worker.current_snapshot().snapshot_id == first.snapshot_id  # still inside 5h window
    clock.advance(hours=3)
    with pytest.raises(StaleSnapshotError):
        worker.current_snapshot()
    warehouse.om_fail = False  # recovery
    assert worker.run_once().status == "published"
    assert worker.current_snapshot().snapshot_id != first.snapshot_id


def test_current_snapshot_before_any_publication_raises(env):
    assert pytest.raises(NoSnapshotError, env[4]().current_snapshot)


def test_index_hook_failure_leaves_pointer_on_previous_snapshot_and_retry_is_idempotent(env):
    warehouse, clock, registry, published, make = env
    attempts = []

    def flaky(snapshot):
        attempts.append(snapshot.snapshot_id)
        if len(attempts) == 1:
            raise ConnectionError("opensearch down")

    worker = make(on_publish=flaky)
    report = worker.run_once()
    assert report.status == "blocked" and report.blocking_reasons == ("publish hook failed: ConnectionError",)
    with pytest.raises(NoSnapshotError):
        worker.current_snapshot()
    clock.advance(minutes=5)
    retried = worker.run_once()
    assert retried.status == "published" and attempts[0] == attempts[1]
    assert worker.current_snapshot().snapshot_id == attempts[0]


def test_dbt_artifact_source_reads_files_each_run_and_reports_unreadable_artifacts(tmp_path, env):
    warehouse, clock, registry, published, make = env
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(warehouse.manifest()))
    source = DbtArtifactRefreshSource(manifest, ["orders", "customers"])
    worker = make(sources=[source])
    assert worker.run_once().status == "published"
    warehouse.dbt_models["orders"] = _model("orders", description="v2", checksum="c9")
    manifest.write_text(json.dumps(warehouse.manifest()))
    clock.advance(minutes=1)
    report = worker.run_once()
    assert report.sources["dbt"].updated == ("model.shop.orders",)
    manifest.write_text("{not json")
    clock.advance(minutes=1)
    broken = worker.run_once()
    assert broken.sources["dbt"].status == "failed" and "unreadable" in broken.sources["dbt"].error


def test_worker_requires_unique_named_sources(env):
    warehouse, _, _, _, make = env
    with pytest.raises(ValueError):
        make(sources=[])
    with pytest.raises(ValueError):
        make(sources=[warehouse.dbt_source(), warehouse.dbt_source()])


# ---- ontology source ----


def _ontology(tmp_path, *, lifecycle="certified", label="Revenue", extra_node=False, tenant="tenant-a", observed=START):
    from packages.platform_contracts.ontology import OntologyEdge, OntologyNode, OntologyProvenance, OntologySnapshot

    provenance = (
        OntologyProvenance(
            source_system="git",
            source_id="ontology.json",
            source_version="abc123",
            observed_at=observed,
            fingerprint="f" * 64,
        ),
    )
    nodes = [
        OntologyNode(
            node_id="revenue",
            tenant_id=tenant,
            node_type="metric",
            label=label,
            lifecycle=lifecycle,
            valid_from=START,
            provenance=provenance,
            attributes={"aliases": ["sales"]},
        ),
        OntologyNode(
            node_id="orders",
            tenant_id=tenant,
            node_type="dataset",
            label="Orders",
            lifecycle="certified",
            valid_from=START,
            provenance=provenance,
        ),
    ]
    if extra_node:
        nodes.append(
            OntologyNode(
                node_id="refunds",
                tenant_id=tenant,
                node_type="metric",
                label="Refunds",
                lifecycle="candidate",
                valid_from=START,
                provenance=provenance,
            )
        )
    edges = (
        OntologyEdge(
            edge_id="e1",
            tenant_id=tenant,
            edge_type="depends_on",
            from_node_id="revenue",
            to_node_id="orders",
            valid_from=START,
            provenance=provenance,
        ),
    )
    snapshot = OntologySnapshot(
        snapshot_id="ont-1", tenant_id=tenant, captured_at=observed, nodes=tuple(nodes), edges=edges
    )
    path = tmp_path / "ontology.json"
    path.write_text(snapshot.model_dump_json())
    return path


def test_ontology_is_embedded_verbatim_and_never_promoted(env, tmp_path):
    from app.context import OntologyFileRefreshSource

    warehouse, clock, registry, published, make = env
    path = _ontology(tmp_path, lifecycle="candidate")
    worker = make(ontology_source=OntologyFileRefreshSource(path, tenant_id="tenant-a"))
    report = worker.run_once()
    assert report.status == "published" and report.ontology.added == ("edge:e1", "orders", "revenue")
    ontology = worker.current_snapshot().ontology
    assert {n.node_id: n.lifecycle for n in ontology.nodes} == {"revenue": "candidate", "orders": "certified"}
    assert ontology.tenant_id == "tenant-a"


def test_ontology_change_republishes_and_provenance_clock_drift_does_not(env, tmp_path):
    from app.context import OntologyFileRefreshSource

    warehouse, clock, registry, published, make = env
    path = _ontology(tmp_path)
    worker = make(ontology_source=OntologyFileRefreshSource(path, tenant_id="tenant-a"))
    first = worker.run_once()
    _ontology(tmp_path, observed=START + timedelta(hours=1))  # re-export, same content
    clock.advance(hours=1)
    assert worker.run_once().status == "unchanged"
    _ontology(tmp_path, label="Net revenue", extra_node=True)
    clock.advance(hours=1)
    changed = worker.run_once()
    assert changed.status == "published" and changed.snapshot_id != first.snapshot_id
    assert changed.ontology.updated == ("revenue",) and changed.ontology.added == ("refunds",)
    _ontology(tmp_path, label="Net revenue")  # refunds dropped from the graph
    clock.advance(hours=1)
    assert worker.run_once().ontology.removed == ("refunds",)
    assert "refunds" not in {n.node_id for n in worker.current_snapshot().ontology.nodes}


def test_ontology_failure_reuses_last_good_then_blocks_when_stale(env, tmp_path):
    from app.context import OntologyFileRefreshSource

    warehouse, clock, registry, published, make = env
    path = _ontology(tmp_path)
    worker = make(
        ontology_source=OntologyFileRefreshSource(path, tenant_id="tenant-a"),
        policy=StalenessPolicy(max_source_age=timedelta(hours=2), max_snapshot_age=timedelta(hours=24)),
    )
    first = worker.run_once()
    path.write_text("{broken")
    clock.advance(hours=1)
    report = worker.run_once()
    assert report.ontology.status == "failed" and report.status == "unchanged"
    assert worker.current_snapshot().ontology is not None
    clock.advance(hours=2)
    stale = worker.run_once()
    assert stale.status == "blocked" and "stale ontology" in stale.blocking_reasons
    assert stale.ontology.status == "reused_stale"
    assert worker.current_snapshot().snapshot_id == first.snapshot_id


def test_ontology_wrong_tenant_and_empty_fetch_are_failures(env, tmp_path):
    from app.context import OntologyFileRefreshSource
    from packages.platform_contracts.ontology import OntologySnapshot

    warehouse, clock, registry, published, make = env
    wrong = _ontology(tmp_path, tenant="tenant-b")
    worker = make(ontology_source=OntologyFileRefreshSource(wrong, tenant_id="tenant-a"))
    report = worker.run_once()
    assert report.status == "published" and report.ontology.status == "failed"
    assert "tenant" in report.ontology.error and worker.current_snapshot().ontology is None

    path = _ontology(tmp_path)
    worker = make(ontology_source=OntologyFileRefreshSource(path, tenant_id="tenant-a"))
    worker.run_once()
    path.write_text(OntologySnapshot(snapshot_id="ont-2", tenant_id="tenant-a").model_dump_json())
    clock.advance(minutes=5)
    emptied = worker.run_once()
    assert emptied.ontology.status == "failed" and emptied.ontology.error == "empty fetch after populated state"
    assert worker.current_snapshot().ontology.nodes


def test_worker_rejects_ontology_from_a_source_that_ignores_the_tenant(env, tmp_path):
    from app.context import OntologyFileRefreshSource

    warehouse, clock, registry, published, make = env
    liar = OntologyFileRefreshSource(_ontology(tmp_path, tenant="tenant-b"), tenant_id="tenant-b")
    report = make(ontology_source=liar).run_once()
    assert report.ontology.error == "ontology tenant does not match the refresh tenant"
    assert report.status == "published"


# ---- the resolution node reads the published ontology ----


def _resolve(registry, snapshot_id, *, tenant="tenant-a", metric="sales"):
    from types import SimpleNamespace

    from test_ads040_execution_gateways import _contract, _intent

    from app.runtime import SnapshotOntologyProvider, ontology_resolution_node
    from packages.platform_contracts.agent_runtime import NodeInput, RunBudget

    contracts = SimpleNamespace(get_certified=lambda *_: SimpleNamespace(contract=_contract()))
    intent = _intent(
        metrics=[{"metric_id": metric}], dataset_id="orders", group_by=[], filters=[], time_range=None, sort=[]
    )
    node_input = NodeInput(
        run_id="run-1",
        tenant_id=tenant,
        purpose="analysis",
        node_id="resolve",
        state_version=1,
        context_snapshot_id=snapshot_id,
        payload={"intent": intent.model_dump(mode="json")},
        remaining_budget=RunBudget(deadline=START + timedelta(hours=1)),
    )
    return ontology_resolution_node(contracts, SnapshotOntologyProvider(registry))(node_input)


def test_resolution_node_resolves_aliases_from_the_published_snapshot(env, tmp_path):
    from app.context import OntologyFileRefreshSource

    warehouse, clock, registry, published, make = env
    worker = make(ontology_source=OntologyFileRefreshSource(_ontology(tmp_path), tenant_id="tenant-a"))
    snapshot_id = worker.run_once().snapshot_id
    output = _resolve(registry, snapshot_id)
    assert output.status == "completed" and output.next_node == "plan"
    assert output.payload["intent"]["metrics"][0]["metric_id"] == "revenue"  # alias "sales" -> certified ID
    assert output.evidence[0].evidence_id == f"ontology:{snapshot_id}:orders"


def test_resolution_node_refuses_candidate_missing_and_foreign_ontologies(env, tmp_path):
    from app.context import OntologyFileRefreshSource

    warehouse, clock, registry, published, make = env
    candidate = make(
        ontology_source=OntologyFileRefreshSource(_ontology(tmp_path, lifecycle="candidate"), tenant_id="tenant-a")
    )
    refused = _resolve(registry, candidate.run_once().snapshot_id)
    assert (
        refused.status == "failed" and refused.error.message_reference == "ontology:unknown_or_uncertified_semantic_id"
    )

    bare = make(tenant_id="tenant-n", ontology_source=None)
    bare_id = bare.run_once().snapshot_id  # published without an ontology
    failed = _resolve(registry, bare_id, tenant="tenant-n")
    assert failed.status == "failed" and failed.error.message_reference == "ontology:LookupError"

    certified = make(
        tenant_id="tenant-a", ontology_source=OntologyFileRefreshSource(_ontology(tmp_path), tenant_id="tenant-a")
    )
    snapshot_id = certified.run_once().snapshot_id
    assert _resolve(registry, snapshot_id, tenant="tenant-b").status == "failed"  # tenant-scoped lookup
    assert _resolve(registry, "refresh:tenant-a:unknown").status == "failed"


# ---- run bootstrap selects and pins the published snapshot ----


def _start(worker, *, purposes=("analysis",), tenant="tenant-a", purpose="analysis", **kwargs):
    from app.runtime import BootstrapRequest, new_governed_run_state
    from packages.platform_contracts.agent_runtime import RunBudget
    from packages.platform_contracts.security import AnalyticsIdentity

    request = BootstrapRequest(
        request_id="req-1",
        request_text="  show revenue  ",
        identity=AnalyticsIdentity(tenant_id=tenant, user_id="u1", purposes=list(purposes)),
    )
    return new_governed_run_state(
        worker,
        request,
        run_id="run-1",
        purpose=purpose,
        budget=RunBudget(deadline=START + timedelta(hours=12)),
        **kwargs,
    )


def test_run_state_pins_the_current_verified_snapshot(env, tmp_path):
    from app.context import OntologyFileRefreshSource

    warehouse, clock, registry, published, make = env
    worker = make(ontology_source=OntologyFileRefreshSource(_ontology(tmp_path), tenant_id="tenant-a"))
    first = worker.run_once().snapshot_id
    state = _start(worker)
    assert state.context_snapshot_id == first and state.graph_version == "graph-v2"
    assert state.request_text == "show revenue" and state.current_node == "create"
    assert _resolve(registry, state.context_snapshot_id).status == "completed"

    warehouse.om_tables["payments"]["description"] = "p2"
    clock.advance(minutes=10)
    second = worker.run_once().snapshot_id
    assert second != first
    assert _start(worker).context_snapshot_id == second  # new runs float forward
    assert state.context_snapshot_id == first  # an existing run stays pinned (resume/replay)


def test_run_start_fails_closed_before_any_run_exists(env, tmp_path):
    from app.context import OntologyFileRefreshSource
    from app.runtime import SnapshotSelectionError

    warehouse, clock, registry, published, make = env
    ontology_source = OntologyFileRefreshSource(_ontology(tmp_path), tenant_id="tenant-a")
    worker = make(ontology_source=ontology_source)
    with pytest.raises(SnapshotSelectionError) as caught:
        _start(worker)
    assert caught.value.code == "snapshot_unavailable"

    worker.run_once()
    clock.advance(hours=25)  # nothing has re-verified the snapshot within policy
    with pytest.raises(SnapshotSelectionError) as caught:
        _start(worker)
    assert caught.value.code == "snapshot_stale"

    with pytest.raises(SnapshotSelectionError) as caught:
        _start(worker, purposes=("reporting",))
    assert caught.value.code == "purpose_not_authorized"

    clock.advance(minutes=1)
    worker.run_once()
    with pytest.raises(SnapshotSelectionError) as caught:
        _start(worker, tenant="tenant-b")  # a tenant-a worker never serves another tenant
    assert caught.value.code == "snapshot_tenant_mismatch"


def test_snapshot_without_ontology_is_refused_unless_explicitly_allowed(env):
    from app.runtime import SnapshotSelectionError

    warehouse, clock, registry, published, make = env
    worker = make()
    worker.run_once()
    with pytest.raises(SnapshotSelectionError) as caught:
        _start(worker)
    assert caught.value.code == "snapshot_has_no_ontology"
    assert _start(worker, require_ontology=False).context_snapshot_id == worker.current_snapshot().snapshot_id
