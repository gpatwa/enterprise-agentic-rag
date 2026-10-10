# ADR-EA-003: Enterprise Identity Integration Strategy

Status: Accepted for EA-041 and EA-042 local implementation

## Decision

Use OIDC/JWT as the analytics API authentication boundary. Validate issuer,
audience, expiry, subject, tenant, groups, and signing-key ID. Load JWKS through
an injected provider and retain overlapping keys during rotation. Never infer a
tenant or user from environment defaults.

Use an enterprise identity broker for SAML and SCIM rather than implementing
SAML parsing or directory provisioning inside the analytics service. The broker
normalizes SAML assertions into OIDC tokens and exposes SCIM lifecycle events;
the service consumes only the resulting claims and records lifecycle audit
events.

## Consequences

- OIDC negative-token tests are local and deterministic.
- Customer IdP metadata, certificate rotation, SAML mappings, and SCIM
  lifecycle drills remain external integration gates.
- Broker outage behavior must fail closed for new sessions while existing
  short-lived tokens follow the configured expiry policy.
- Group-to-purpose mapping is tenant configuration and requires security-owner
  approval; it is not inferred from prompt text.
