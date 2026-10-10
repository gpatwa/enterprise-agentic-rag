# ADS-031: Identity and Request Bootstrap

Status: **Complete**
Milestone: M3
Depends on: ADS-030

## Deliverable

`services/analytics-api/app/runtime/bootstrap.py` provides a bootstrap node
factory bound to a validated `AnalyticsIdentity` and bounded request. It checks
request ID, tenant identity, and purpose authorization before advancing to
`retrieve`. Mismatches return a typed policy denial, so the governed graph
runner terminalizes the request before retrieval.

The request is stored in the versioned run state and supplied to downstream
nodes. Request content is not copied into evidence; evidence fingerprints are
SHA-256 digests. Input and state contracts constrain request text to 2,000
characters.

## Evidence

- `packages/platform_contracts/agent_runtime.py`
- `services/analytics-api/app/runtime/bootstrap.py`
- `services/analytics-api/app/runtime/graph_runner.py`
- `services/analytics-api/app/harness/graph.py`
- Static validation: Ruff and `git diff --check` pass.

## Boundary

The bootstrap node assumes its `AnalyticsIdentity` came from a trusted
authentication layer. It does not validate bearer tokens, resolve group claims,
or replace the OIDC adapter. Those integrations and their negative suites are
separate work (including ADS-063). This milestone does not open a live model,
retrieval provider, warehouse, or execution tool.
