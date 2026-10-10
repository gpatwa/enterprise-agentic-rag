# ADS-006: Routing Flags

Status: Review
Milestone: M0
Depends on: ADS-003
Scope: provider-neutral route selection and governed-action guard

## Objective

Provide a typed, tenant-scoped routing boundary for the legacy analytics path,
shadow comparison, governed execution, and an explicit disabled state. The
default is legacy. Governed execution requires rollout, approval, and audit
context supplied by an authoritative caller; a model or request payload cannot
enable it by itself.

## Contract

`packages.platform_contracts.routing` defines exactly four modes:

| Mode | User-visible result | Governed action | Side effects |
|---|---|---|---|
| `legacy` | legacy result | refused | legacy path only |
| `shadow` | legacy result | refused | comparison recording only |
| `governed` | governed result | allowed after explicit gates | auditable governed path |
| `disabled` | clear refusal | refused | none |

Unknown modes, extra fields, empty tenant keys, forged capability combinations,
and missing governed rollout context fail validation. Tenant overrides are
looked up by exact tenant ID; an unmatched tenant uses the safe `legacy`
default. Mode changes are validated as well; a disabled tenant cannot jump
directly into governed execution.

## Acceptance evidence

- Focused test suite: `12 passed`.
- Unknown mode and forged capability tests fail closed.
- Tenant-scoped selection covers shadow, disabled, and legacy fallback.
- Shadow and disabled routes both fail the governed-action guard.
- Governed route requires rollout ID, approval reference, audit event ID, and
  explicit `governed_enabled=true`.
- Disabled-to-governed mode transitions are rejected.
- `ruff check packages/platform_contracts/routing.py packages/platform_contracts/tests/test_routing.py` passed.
- `ruff format --check packages/platform_contracts/routing.py packages/platform_contracts/tests/test_routing.py` passed.
- `git diff --check` passed.

## Non-goals

- Wiring the contract into the graph runner, API, tool registry, or manifest.
- Persisting rollout configuration or audit events.
- Implementing a provider-specific feature-flag service.
- Allowing automatic promotion or model-controlled governed enablement.

## Residual risks

- The runtime integration packets must consume `RouteDecision` at their actual
  entry points before governed execution is reachable.
- Persistence and operational ownership of rollout approvals and audit events
  remain ADS-005 and later integration work.
- The contract does not itself prove that a legacy adapter has no side effects;
  adapter contracts and operations tests must enforce that boundary.
