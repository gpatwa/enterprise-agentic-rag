# Compass Analytics API

Standalone FastAPI service for guarded text-to-SQL analytics. It owns schema
grounding, LLM configuration, SQL safety, read-only execution, chart result
assembly, and analytics-specific tests.

The service depends on the public v1 models in
`packages/platform_contracts/analytics.py`. It does not import support API
routes, graph state, models, or connectors.

## Contract Evolution

The v1 route remains the current public API. `packages/platform_contracts/
analytics_v2.py` adds a transport-only v2 outcome envelope for answers,
clarifications, refusals, human review, and operational failures. No route has
adopted it yet, so v1 clients remain compatible. A retirement policy will be
set only after v2 routing, evidence persistence, and a customer migration plan
exist.

```json
{"outcome":"answer","query_id":"q-1","tenant_id":"tenant-a","user_id":"user-a","dataset":"olist","answer":"Delivered revenue was BRL 370.00."}
{"outcome":"clarify","query_id":"q-2","tenant_id":"tenant-a","user_id":"user-a","dataset":"olist","questions":[{"id":"period","prompt":"Which period should I use?"}]}
{"outcome":"refuse","query_id":"q-3","tenant_id":"tenant-a","user_id":"user-a","dataset":"olist","reason_code":"unauthorized","explanation":"You are not permitted to access this dataset."}
{"outcome":"review","query_id":"q-4","tenant_id":"tenant-a","user_id":"user-a","dataset":"olist","review_id":"review-1","risk_reasons":["uncertified metric"],"expires_at":"2026-08-21T00:00:00Z","allowed_actions":["approve","reject"]}
{"outcome":"failed","query_id":"q-5","tenant_id":"tenant-a","user_id":"user-a","dataset":"olist","error_code":"query_timeout","message":"The warehouse did not respond in time.","retryable":true}
```

V2 evidence can cite versioned metadata assets, filters, generated SQL, result
fingerprints, freshness, model and prompt versions, and a policy decision. It
intentionally excludes chain-of-thought, credentials, and raw source data. The
remaining ADR questions are evidence retention, result-fingerprint format, and
the authority that records reviewer identity.

## Analytics Control Store

Analytics owns a separate control-store schema for versioned query outcomes and
public evidence. Set `ANALYTICS_CONTROL_DB_URL`; never point it at the customer
warehouse configured through `ANALYTICS_DB_URL`.

```bash
cd services/analytics-api
ANALYTICS_CONTROL_DB_URL=sqlite:///analytics-control.db alembic upgrade head
ANALYTICS_CONTROL_DB_URL=sqlite:///analytics-control.db alembic downgrade base
```

## Semantic Contracts

`packages/platform_contracts/semantic.py` defines the versioned, portable
semantic contract used by the future registry and compiler. It models datasets,
physical fields, entities and grain, dimensions, certified metrics, approved
joins, required filters, policy references, and owners. Contracts contain no
warehouse SQL and reject unknown or cross-dataset references when loaded.

`packages/platform_contracts/analytics_intent.py` adds the dialect-neutral
intent IR that planners will emit: semantic metric/dimension/field IDs, time
range, filters, ordering, and result limit. It contains no raw SQL and can be
validated against an exact semantic-contract version before compilation.

The EA-013 PostgreSQL compiler spike is intentionally limited to the certified
single-dataset subset. Its comparison with Cube Core is recorded in
`docs/adr/ADR-EA-002-cube-core-vs-internal-compiler.md`; joins and policy
injection remain explicit later milestones.

EA-014 exposes that compiler through `CertifiedIntentCompiler`, which resolves
the exact certified registry document before compiling. The current route is
unchanged until the later planner and execution milestones are complete.
Compiler adapters are selected by dialect through `CompilerRegistry`; a second
provider can register without changing intent or planner contracts.

## Local Development

```bash
make install-analytics
make seed-olist
make dev-analytics-api
```

The API listens on http://localhost:8090. Configure it from
`services/analytics-api/.env.example`.

```bash
make test-analytics
curl http://localhost:8090/health
curl -X POST http://localhost:8090/api/v1/analytics/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"Revenue by month"}'
```

`ANALYTICS_API_KEY` is optional for local development. When set, clients must
send the value in `X-API-Key`.

For the product-style local stack, startup provisions OpenSearch, creates the
`context-v1` index mapping, loads the certified local semantic contract, and
creates the matching OpenSearch Dashboards index pattern:

```bash
docker compose --profile analytics up --build -d
curl http://localhost:8090/health
```

No dashboard setup or seed command is required. The health response reports
`context_index_ready`, `context_documents_indexed`, and `dashboard_ready`.

## Local Context Verification

The M1 context layer can be verified against the local OpenSearch profile
without Azure or an LLM key:

```bash
make verify-context-local
```

The drill creates a disposable `context-m1-verify` index, indexes certified and
uncertified assets for two tenants, verifies tenant and certification filters,
checks snapshot fingerprint round-trip, and confirms stale metadata is blocked.
Stop the local profile with `docker compose --profile analytics down` when done.
