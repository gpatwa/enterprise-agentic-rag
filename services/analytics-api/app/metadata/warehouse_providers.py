"""Read-only Snowflake and Databricks metadata providers over an injected query runner.

The runner executes one parameterized SELECT with `:name` markers and returns rows; it owns the driver,
the credentials (a read-only role) and marker translation. These providers issue a single fixed query
against `information_schema.columns`. Only the database or catalog name is placed in the SQL text, after
the same quoting and character checks the compilers use; the schema and table travel as bind values.
Names are matched exactly as given: Snowflake stores unquoted names in upper case, so pass the stored case.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from app.compiler.dialects import DATABRICKS, SNOWFLAKE, SQLDialect
from packages.platform_contracts.metadata import (
    MetadataAsset,
    MetadataColumn,
    MetadataSnapshot,
)

QueryRunner = Callable[[str, Mapping[str, Any]], Sequence[Sequence[Any]]]

_COLUMNS_QUERY = (
    "SELECT column_name, data_type, is_nullable "
    "FROM {catalog}.information_schema.columns "
    "WHERE table_schema = :table_schema AND table_name = :table_name "
    "ORDER BY ordinal_position"
)


class _InformationSchemaProvider:
    provider_name = ""
    _dialect: SQLDialect

    def __init__(self, run: QueryRunner, *, catalog: str, schema: str) -> None:
        if not schema or not schema.strip():
            raise ValueError("schema must be non-blank")
        self._run = run
        self._catalog_sql = self._dialect.quote_identifier(catalog)  # validates and quotes
        self._catalog = catalog
        self._schema = schema

    def get_snapshot(self, asset_name: str) -> MetadataSnapshot:
        if not asset_name or not asset_name.strip():
            raise ValueError("asset_name must be non-blank")
        rows = self._run(
            _COLUMNS_QUERY.format(catalog=self._catalog_sql),
            {"table_schema": self._schema, "table_name": asset_name},
        )
        if not rows:
            # No rows means the table is missing or the role cannot see it; do not return an empty asset.
            raise LookupError(f"asset not found or not visible: {self._catalog}.{self._schema}.{asset_name}")
        return MetadataSnapshot(
            provider=self.provider_name,
            assets=[
                MetadataAsset(
                    id=f"{self._catalog}.{self._schema}.{asset_name}",
                    display_name=asset_name,
                    physical_name=asset_name,
                    provider=self.provider_name,
                    columns=[
                        MetadataColumn(
                            name=str(name),
                            data_type=str(data_type),
                            nullable=str(nullable).upper() != "NO",
                        )
                        for name, data_type, nullable in rows
                    ],
                    observed_at=datetime.now(timezone.utc),
                )
            ],
        )


class SnowflakeMetadataProvider(_InformationSchemaProvider):
    provider_name = "snowflake"
    _dialect = SNOWFLAKE

    def __init__(self, run: QueryRunner, *, database: str, schema: str) -> None:
        super().__init__(run, catalog=database, schema=schema)


class DatabricksMetadataProvider(_InformationSchemaProvider):
    """Unity Catalog: `catalog` is the first level of catalog.schema.table."""

    provider_name = "databricks"
    _dialect = DATABRICKS

    def __init__(self, run: QueryRunner, *, catalog: str, schema: str) -> None:
        super().__init__(run, catalog=catalog, schema=schema)
