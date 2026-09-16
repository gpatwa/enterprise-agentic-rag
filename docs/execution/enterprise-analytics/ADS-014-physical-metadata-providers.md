# ADS-014: PostgreSQL and DuckDB Providers

Status: **Complete**
Milestone: M1
Depends on: ADS-010

## Deliverable

The existing PostgreSQL inspector and new `DuckDBMetadataProvider` expose
normalized physical columns through the shared snapshot contract. DuckDB uses
read-only connections and rejects database paths outside an explicit allowlist.

## Evidence

- `services/analytics-api/app/metadata/providers.py`
- `services/analytics-api/tests/test_metadata_providers.py`
- PostgreSQL column/nullability and DuckDB read-only/allowlisted-path tests
  pass.

## Boundary

Physical providers inspect schema only. They do not write data, execute
generated queries, or bypass tenant, policy, or semantic certification gates.
