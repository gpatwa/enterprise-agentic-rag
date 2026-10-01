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
