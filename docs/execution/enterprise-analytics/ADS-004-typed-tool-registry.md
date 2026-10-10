# ADS-004: Typed Tool Registry

**Status:** Review

## Objective

Define a provider-neutral, fail-closed registry for the tools that an agent
graph may reference. The registry is a declaration and compatibility boundary;
it is not an executor or an authorization service.

## Delivered

- `ToolSpec` with stable identity/version, capability, risk class, timeout,
  retry policy, idempotency requirements, contract versions, and scope.
- `ToolRegistry` with duplicate detection, exact version lookup, contract
  compatibility checks, unsafe-capability rejection, and metadata-only output.
- Pydantic validation rejects malformed identities, versions, timeouts, risk,
  retry, and idempotency metadata.

## Scope and non-goals

This packet covers declaration, registration, and lookup of tool metadata.
Execution adapters, policy authorization, tenant identity resolution,
checkpointing, routing, and provider implementations are intentionally deferred
to later packets. Raw model-generated SQL is not a supported tool capability.

## Acceptance evidence

Focused tests cover valid registration/lookup, undeclared and unsupported
versions, duplicate identities, incompatible contracts, invalid risk/timeout/
idempotency metadata, destructive scope requirements, unsafe capabilities, and
the absence of execution behavior.

## Residual risks

The registry is not yet wired into the graph runner or authorization path.
Production deployments still need a signed/versioned registry distribution,
policy-to-capability mapping, and integration tests proving every execution
request passes through both registry lookup and policy approval.
