"""Local reference stack (ADS-048): the governed v2 runtime wired end to end with fakes only.

Nothing here contacts a network service. DuckDB is real and embedded; the "PostgreSQL" journey
runs the real PostgresGateway and PostgreSQL compiler against an emulated engine, so Postgres
SQL, read-only/timeout statements, and cost gating are exercised but no server is.
"""
