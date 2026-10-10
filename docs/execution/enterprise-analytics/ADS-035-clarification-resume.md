# ADS-035: Clarification and Resume

Status: **Complete**
Milestone: M3
Depends on: ADS-034

## Deliverable

Clarification state is scoped to the original request, run, tenant, and
purpose. The controller accepts only a candidate from the ambiguity set,
requires the same authorized identity on resume, and caps the whole run at two
continuations. The graph pauses at a clarification node and resumes the same
durable run with the selected candidate; a changed request fingerprint,
identity, purpose, or candidate is rejected.

## Evidence

- `services/analytics-api/app/runtime/clarification.py`
- `packages/platform_contracts/analytics_planning.py`
- `services/analytics-api/app/runtime/graph_runner.py`
- Static validation: Ruff and `git diff --check` pass.

## Boundary

The future API/MCP layer must authenticate the caller and invoke
`resume_clarification` before passing its typed state to `AgentGraphRunner`.
This packet does not expose a public resume endpoint.
