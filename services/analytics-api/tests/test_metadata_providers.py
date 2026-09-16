"""Normalization tests for catalog metadata providers and quality ranking."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from sqlalchemy import create_engine, text

from app.metadata import (
    DbtManifestProvider,
    DuckDBMetadataProvider,
    MetadataQualityGate,
    OpenMetadataProvider,
    PostgresMetadataProvider,
    rank_assets,
)
from packages.platform_contracts.metadata import MetadataAsset, MetadataSnapshot


def test_postgres_provider_normalizes_columns():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE orders (id INTEGER NOT NULL, status TEXT)"))

    snapshot = PostgresMetadataProvider(engine, schema=None).get_snapshot("orders")

    assert snapshot.provider == "postgres"
    assert [(column.name, column.nullable) for column in snapshot.assets[0].columns] == [
        ("id", False),
        ("status", True),
    ]


def test_dbt_provider_merges_manifest_and_catalog_details():
    provider = DbtManifestProvider(
        {
            "nodes": {
                "model.demo.orders": {
                    "resource_type": "model",
                    "name": "orders",
                    "alias": "fct_orders",
                    "description": "Certified order facts",
                    "tags": ["sales"],
                    "meta": {"owner": "analytics", "certified": True},
                    "columns": {"id": {"description": "Order identifier"}},
                }
            }
        },
        {"nodes": {"model.demo.orders": {"columns": {"id": {"type": "integer"}}}}},
    )

    asset = provider.get_snapshot("orders").assets[0]

    assert asset.physical_name == "fct_orders"
    assert asset.owner_ids == ["analytics"]
    assert asset.columns[0].data_type == "integer"


def test_dbt_provider_normalizes_tests_exposures_metrics_lineage_and_quality():
    provider = DbtManifestProvider(
        {
            "nodes": {
                "model.demo.orders": {
                    "resource_type": "model", "name": "orders", "columns": {},
                    "depends_on": {"nodes": ["model.demo.customers", "test.demo.orders_id"]},
                    "checksum": {"checksum": "abc123"},
                },
                "test.demo.orders_id": {"resource_type": "test", "name": "orders_id_not_null", "depends_on": {"nodes": ["model.demo.orders"]}},
            },
            "exposures": {"exposure.demo.dashboard": {"name": "sales_dashboard", "type": "dashboard", "depends_on": {"nodes": ["model.demo.orders"]}}},
            "metrics": {"metric.demo.revenue": {"name": "revenue", "label": "Revenue", "calculation_method": "sum", "depends_on": {"nodes": ["model.demo.orders"]}}},
        },
        {"nodes": {"model.demo.orders": {"stats": {"row_count": {"value": 42}}}}},
        {"results": [{"unique_id": "model.demo.orders", "status": "success", "timing": [{"started_at": "2026-09-15T12:00:00+00:00"}]}]},
    )

    asset = provider.get_snapshot("orders").assets[0]

    assert asset.upstream_asset_ids == ["model.demo.customers", "test.demo.orders_id"]
    assert asset.tests[0].name == "orders_id_not_null"
    assert asset.exposures[0].name == "sales_dashboard"
    assert asset.metrics[0].expression == "sum"
    assert asset.quality and asset.quality.row_count == 42
    assert asset.freshness and asset.freshness.last_updated_at is not None


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(self):
        self.urls: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse(
            {
                "data": {
                    "fullyQualifiedName": "warehouse.orders",
                    "displayName": "Orders",
                    "description": "Certified order facts",
                    "owner": {"name": "analytics"},
                    "certification": {"tagLabel": "Gold"},
                    "tags": [{"tagFQN": "Tier.Gold"}],
                    "columns": [{"name": "id", "dataType": "INT", "constraint": "NOT NULL"}],
                }
            }
        )


def test_openmetadata_provider_normalizes_catalog_response():
    client = FakeClient()
    snapshot = OpenMetadataProvider("https://metadata.example/", "token", client).get_snapshot("orders")

    assert client.urls == ["https://metadata.example/api/v1/tables/name/orders"]
    assert snapshot.assets[0].certified is True
    assert snapshot.assets[0].columns[0].nullable is False


def test_openmetadata_provider_maps_lineage_glossary_quality_and_classification():
    class RichClient(FakeClient):
        def get(self, url: str) -> FakeResponse:
            response = super().get(url)
            response.payload["data"]["upstreamLineage"] = [{"fullyQualifiedName": "warehouse.customers"}]
            response.payload["data"]["glossaryTerms"] = [{"fullyQualifiedName": "Sales.Revenue", "displayName": "Revenue", "description": "Recognized sales"}]
            response.payload["data"]["quality"] = {"completeness": 0.99, "nullRate": 0.01, "rowCount": 100}
            response.payload["data"]["freshness"] = {"intervalSeconds": 3600, "stale": False}
            response.payload["data"]["tags"].append({"tagFQN": "Classification.Confidential"})
            return response

    asset = OpenMetadataProvider("https://metadata.example", "token", RichClient()).get_snapshot("orders").assets[0]

    assert asset.upstream_asset_ids == ["warehouse.customers"]
    assert asset.glossary_terms[0].name == "Revenue"
    assert asset.quality and asset.quality.row_count == 100
    assert asset.freshness and asset.freshness.expected_interval_seconds == 3600
    assert asset.classification == "confidential"


def test_duckdb_provider_is_read_only_and_path_allowlisted(tmp_path: Path):
    database = tmp_path / "warehouse.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("CREATE TABLE orders (id INTEGER NOT NULL, status VARCHAR)")
    connection.close()

    snapshot = DuckDBMetadataProvider(database, allowed_paths=(tmp_path,)).get_snapshot("orders")
    assert snapshot.provider == "duckdb"
    assert [(column.name, column.nullable) for column in snapshot.assets[0].columns] == [("id", False), ("status", True)]
    with pytest.raises(PermissionError):
        DuckDBMetadataProvider(database, allowed_paths=(tmp_path / "other",))


def test_quality_gate_and_ranking_are_deterministic():
    complete = MetadataAsset(
        id="orders",
        display_name="Orders",
        physical_name="fct_orders",
        provider="dbt",
        description="Certified order facts",
        owner_ids=["analytics"],
        certified=True,
        columns=[{"name": "order_id", "data_type": "integer"}],
        tags=["sales"],
    )
    incomplete = complete.model_copy(update={"id": "orders_raw", "certified": False, "owner_ids": []})
    snapshot = MetadataSnapshot(provider="dbt", assets=[incomplete, complete])

    assert MetadataQualityGate().evaluate(complete).actionable is True
    assert MetadataQualityGate().evaluate(incomplete).missing == ["owner", "certification"]
    assert [result.asset.id for result in rank_assets("sales orders", snapshot)] == ["orders", "orders_raw"]
