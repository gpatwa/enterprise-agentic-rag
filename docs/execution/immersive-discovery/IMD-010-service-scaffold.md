# IMD-010: Independent Discovery API Scaffold

## Objective

Create the smallest independently importable FastAPI discovery service and
focused health test. It establishes the product boundary without implementing
catalog, search, events, persistence, ranking, or UI behavior.

## Dependencies

- IMD-001 is merged at `e5c679d`.
- IMD-003 is merged at `1aebc9e`.
- The current branch contains the IMD-004 checkpoint.

## Read First

1. `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`
2. `docs/adr/ADR-IMD-001-immersive-discovery.md`
3. `packages/platform_contracts/discovery.py`
4. `services/analytics-api/app/main.py`
5. `services/analytics-api/Dockerfile`
6. `services/analytics-api/requirements.txt`
7. `docs/execution/immersive-discovery/IMD-010-service-scaffold.md`

Do not read unrelated repository files.

## Owned Files

- Create `services/discovery-api/app/__init__.py`.
- Create `services/discovery-api/app/main.py`.
- Create `services/discovery-api/requirements.txt` with only the minimal pinned
  FastAPI, Uvicorn, and Pydantic runtime dependencies.
- Create `services/discovery-api/tests/test_health.py`.

Do not create a Dockerfile, Compose service, configuration system, routes
beyond health, database client, OpenSearch client, provider adapter, or UI.

## Service Requirements

- Expose a FastAPI app as `app.main:app`.
- Provide `GET /health` returning a stable local service identity and `ok`
  status.
- Import only shared platform contracts; do not import `services/api`,
  `services/analytics-api`, or their domain modules.
- Keep startup/shutdown side-effect free and local-test friendly.
- Pin versions compatible with the repository's Python 3.10 baseline.

## Acceptance Evidence

- `app.main:app` imports from the discovery service path.
- Health response is deterministic and tested with FastAPI's local test client.
- Requirements contain no OpenSearch, database, LLM, support, or analytics
  dependency.
- Import smoke test proves support and analytics product modules are absent.
- No network, database, filesystem migration, or cloud resource is required.
- Focused tests, Ruff, and `git diff --check` pass.

## Targeted Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_health.py -q
ruff check services/discovery-api/app services/discovery-api/tests
git diff --check
```

## Stop Conditions

Stop if a health endpoint requires importing current support/analytics startup
code, a dependency requires Python newer than 3.10, or runtime wiring would
need Compose/deployment work owned by IMD-080.

## Commit

```text
feat(discovery): IMD-010 scaffold discovery api
```

