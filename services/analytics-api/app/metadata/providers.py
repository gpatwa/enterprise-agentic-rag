"""Metadata provider protocols and read-only normalizing adapters."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy import inspect

from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.metadata import (
    MetadataAsset,
    MetadataColumn,
    MetadataExposure,
    MetadataFreshness,
    MetadataGlossaryTerm,
    MetadataMetric,
    MetadataQualitySignals,
    MetadataSnapshot,
    MetadataTest,
)
from packages.platform_contracts.semantic import SemanticContract, SemanticPolicy


class MetadataProvider(Protocol):
    provider_name: str

    def get_snapshot(self, asset_name: str) -> MetadataSnapshot:
        ...


class SemanticModelProvider(Protocol):
    def get_contract(self, contract_id: str, version: str) -> SemanticContract:
        ...


class PolicyProvider(Protocol):
    def get_policies(self, contract: SemanticContract) -> list[SemanticPolicy]:
        ...


class PostgresMetadataProvider:
    provider_name = "postgres"

    def __init__(self, engine: Any, schema: str | None = "public"):
        self.engine = engine
        self.schema = schema

    def get_snapshot(self, asset_name: str) -> MetadataSnapshot:
        inspector = inspect(self.engine)
        columns = [
            MetadataColumn(
                name=column["name"],
                data_type=str(column["type"]),
                nullable=bool(column.get("nullable", True)),
            )
            for column in inspector.get_columns(asset_name, schema=self.schema)
        ]
        return MetadataSnapshot(
            provider=self.provider_name,
            assets=[
                MetadataAsset(
                    id=f"{self.schema}.{asset_name}",
                    display_name=asset_name,
                    physical_name=asset_name,
                    provider=self.provider_name,
                    columns=columns,
                    observed_at=datetime.now(timezone.utc),
                )
            ],
        )


class DbtManifestProvider:
    provider_name = "dbt"

    def __init__(
        self,
        manifest: dict[str, Any],
        catalog: dict[str, Any] | None = None,
        run_results: dict[str, Any] | None = None,
    ):
        self.manifest = manifest
        self.catalog = catalog or {}
        self.run_results = run_results or {}

    @classmethod
    def from_files(
        cls,
        manifest_path: Path | str,
        catalog_path: Path | str | None = None,
        run_results_path: Path | str | None = None,
    ) -> "DbtManifestProvider":
        manifest = json.loads(Path(manifest_path).read_text())
        catalog = json.loads(Path(catalog_path).read_text()) if catalog_path else None
        run_results = json.loads(Path(run_results_path).read_text()) if run_results_path else None
        return cls(manifest, catalog, run_results)

    def get_snapshot(self, asset_name: str) -> MetadataSnapshot:
        assets = []
        for node_id, node in self.manifest.get("nodes", {}).items():
            if node.get("resource_type") != "model" or node.get("name") != asset_name:
                continue
            catalog_node = self.catalog.get("nodes", {}).get(node_id, {})
            catalog_columns = catalog_node.get("columns", {})
            result = next(
                (item for item in self.run_results.get("results", []) if item.get("unique_id") == node_id),
                None,
            )
            tests = [
                MetadataTest(
                    name=test.get("name", test_id),
                    status="pass" if test.get("status") == "pass" else "fail" if test.get("status") == "fail" else "not_run",
                    failure_message=test.get("message"),
                )
                for test_id, test in self.manifest.get("nodes", {}).items()
                if test.get("resource_type") == "test" and node_id in test.get("depends_on", {}).get("nodes", [])
            ]
            exposures = [
                MetadataExposure(
                    name=exposure.get("name", exposure_id),
                    exposure_type=exposure.get("type", "dashboard"),
                    owner_ids=[str(exposure.get("owner", {}).get("name"))]
                    if exposure.get("owner", {}).get("name") else [],
                    url=exposure.get("meta", {}).get("url"),
                )
                for exposure_id, exposure in self.manifest.get("exposures", {}).items()
                if node_id in exposure.get("depends_on", {}).get("nodes", [])
            ]
            metrics = [
                MetadataMetric(
                    name=metric.get("name", metric_id), label=metric.get("label"),
                    expression=metric.get("calculation_method"), type=metric.get("type"),
                )
                for metric_id, metric in self.manifest.get("metrics", {}).items()
                if node_id in metric.get("depends_on", {}).get("nodes", [])
            ]
            columns = [
                MetadataColumn(
                    name=name,
                    data_type=str(details.get("type", "unknown")),
                    description=details.get("comment") or info.get("description"),
                )
                for name, info in node.get("columns", {}).items()
                for details in [catalog_columns.get(name, {})]
            ]
            assets.append(
                MetadataAsset(
                    id=node_id,
                    display_name=node.get("name", asset_name),
                    physical_name=node.get("alias") or node.get("name", asset_name),
                    provider=self.provider_name,
                    description=node.get("description"),
                    owner_ids=[str(node.get("meta", {}).get("owner"))] if node.get("meta", {}).get("owner") else [],
                    tags=[str(tag) for tag in node.get("tags", [])],
                    certified=bool(node.get("meta", {}).get("certified", False)),
                    columns=columns,
                    upstream_asset_ids=[str(item) for item in node.get("depends_on", {}).get("nodes", [])],
                    tests=tests,
                    exposures=exposures,
                    metrics=metrics,
                    quality=MetadataQualitySignals(
                        row_count=catalog_node.get("stats", {}).get("row_count", {}).get("value")
                    ) if catalog_node.get("stats", {}).get("row_count", {}).get("value") is not None else None,
                    freshness=MetadataFreshness(
                        last_updated_at=datetime.fromisoformat(result["timing"][0]["started_at"])
                    ) if result and result.get("timing") and result["timing"][0].get("started_at") else None,
                    source_version=str(node.get("checksum", {}).get("checksum")) if node.get("checksum") else None,
                )
            )
        return MetadataSnapshot(provider=self.provider_name, assets=assets)


class OpenMetadataProvider:
    """Read-only OpenMetadata adapter with an injectable HTTP client."""

    provider_name = "openmetadata"

    def __init__(self, base_url: str, token: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(headers={"Authorization": f"Bearer {token}"})

    def get_snapshot(self, asset_name: str) -> MetadataSnapshot:
        response = self.client.get(f"{self.base_url}/api/v1/tables/name/{asset_name}")
        response.raise_for_status()
        body = response.json()
        payload = body.get("data", body)
        columns = [
            MetadataColumn(
                name=column.get("name", "unknown"),
                data_type=str(column.get("dataType", "unknown")),
                description=column.get("description"),
                nullable=column.get("constraint", "").upper() != "NOT NULL",
            )
            for column in payload.get("columns", [])
        ]
        owner = payload.get("owner") or {}
        lineage = payload.get("upstreamLineage", []) or payload.get("lineage", {}).get("upstream", [])
        glossary_terms = payload.get("glossaryTerms", [])
        quality_payload = payload.get("quality") or {}
        freshness_payload = payload.get("freshness") or {}
        classifications = [
            str(tag.get("tagFQN", tag)).split(".")[-1].lower()
            for tag in payload.get("tags", [])
            if isinstance(tag, dict) or tag
        ]
        classification = next(
            (value for value in classifications if value in {"public", "internal", "confidential", "restricted"}),
            "internal",
        )
        return MetadataSnapshot(
            provider=self.provider_name,
            assets=[
                MetadataAsset(
                    id=str(payload.get("fullyQualifiedName", asset_name)),
                    display_name=str(payload.get("displayName", asset_name)),
                    physical_name=asset_name,
                    provider=self.provider_name,
                    description=payload.get("description"),
                    owner_ids=[str(owner.get("name"))] if owner.get("name") else [],
                    tags=[str(tag.get("tagFQN", tag)) if isinstance(tag, dict) else str(tag) for tag in payload.get("tags", [])],
                    certified=bool(payload.get("certification")),
                    columns=columns,
                    upstream_asset_ids=[
                        str(item.get("fullyQualifiedName", item.get("name", item)))
                        if isinstance(item, dict) else str(item)
                        for item in lineage
                    ],
                    glossary_terms=[
                        MetadataGlossaryTerm(
                            term_id=str(item.get("fullyQualifiedName", item.get("name", "term"))),
                            name=str(item.get("displayName", item.get("name", "term"))),
                            description=item.get("description"), source="openmetadata",
                        )
                        for item in glossary_terms
                    ],
                    quality=MetadataQualitySignals(
                        completeness=quality_payload.get("completeness"),
                        null_rate=quality_payload.get("nullRate"),
                        row_count=quality_payload.get("rowCount"),
                        issues=[str(item) for item in quality_payload.get("issues", [])],
                    ) if quality_payload else None,
                    freshness=MetadataFreshness(
                        expected_interval_seconds=freshness_payload.get("intervalSeconds"),
                        stale=bool(freshness_payload.get("stale", False)),
                    ) if freshness_payload else None,
                    classification=classification,
                )
            ],
        )


class DuckDBMetadataProvider:
    """Read-only DuckDB provider restricted to an explicit allowlisted path."""

    provider_name = "duckdb"

    def __init__(self, database_path: str | Path, allowed_paths: tuple[str | Path, ...] = ()):
        self.database_path = Path(database_path).expanduser().resolve()
        allowed = tuple(Path(path).expanduser().resolve() for path in allowed_paths)
        if allowed and not any(self.database_path == path or path in self.database_path.parents for path in allowed):
            raise PermissionError("DuckDB database path is outside the allowlist")

    def get_snapshot(self, asset_name: str) -> MetadataSnapshot:
        import duckdb

        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            rows = connection.execute(
                """SELECT column_name, data_type, is_nullable
                FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position""",
                [asset_name],
            ).fetchall()
        finally:
            connection.close()
        return MetadataSnapshot(
            provider=self.provider_name,
            assets=[MetadataAsset(
                id=f"{self.database_path}:{asset_name}", display_name=asset_name, physical_name=asset_name,
                provider=self.provider_name,
                columns=[MetadataColumn(name=name, data_type=data_type, nullable=nullable == "YES") for name, data_type, nullable in rows],
            )],
        )


class GitSemanticModelProvider:
    def __init__(self, registry: SemanticRegistry):
        self.registry = registry

    def get_contract(self, contract_id: str, version: str) -> SemanticContract:
        return self.registry.get_certified(contract_id, version).contract


class ContractPolicyProvider:
    def get_policies(self, contract: SemanticContract) -> list[SemanticPolicy]:
        return list(contract.policies)
