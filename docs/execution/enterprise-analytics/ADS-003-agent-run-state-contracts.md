# ADS-003: Agent Run-State Contracts

Status: **Review**
Depends on: ADS-002
Scope: Versioned graph execution contracts only

## Delivered

- Strict `v1` `AgentRunState` with tenant and purpose scope, graph/node
  identity, context snapshot, bounded transition/cost/deadline budgets, model
  and policy result slots, cancellation, errors, evidence, and terminal outcome.
- Typed `NodeInput` and `NodeOutput` contracts with bounded payloads and
  fail-closed error/result shapes.
- Typed `Transition` contract and the authored M0 legal-transition table.
- Evidence references carry redaction and fingerprints; contracts contain
  references rather than raw customer data or secrets.
- Cancellation, retry/error evidence, and terminal outcomes are explicit.

## Verification

```text
PYTHONPATH=. pytest -q packages/platform_contracts/tests/test_agent_runtime.py
ruff check packages/platform_contracts/agent_runtime.py packages/platform_contracts/tests/test_agent_runtime.py
ruff format --check packages/platform_contracts/agent_runtime.py packages/platform_contracts/tests/test_agent_runtime.py
```

The packet is intentionally left in **Review**. It does not implement a graph
runner, persistence, leases, outbox, routing flags, or shared manifest updates.
