# ADS-063: OIDC Identity and Group Propagation and Delegated-Purpose Policy

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M6 (wave 6A, last of ADS-060, ADS-062, ADS-063)
Depends on: ADS-031, ADS-045

## Decisions confirmed by the user

Wave 6A scope ("go with that scope"): the identity suite runs against the **local test issuer only** (the same suite can later be
pointed at a live provider, which stays off until the user explicitly authorizes it); an agent acting for a person gets only the
intersection of the person's purposes and the agent's allowed purposes; a removed group takes effect on the next request.

Two choices made inside that scope, for the user to confirm or change:
1. **Delegated callers can never decide a review.** A token that names an acting party is an *agent* call, on REST as well as on the
   ADS-060 tool surface. (`api_v2`'s review endpoint now refuses non-human callers with 403 `human_required`; before this packet it
   only refused the requester.)
2. **A delegation grant also carries groups.** The scope named purposes only; letting an agent inherit the person's groups would
   let it reach confidential or restricted data, so a delegated call gets the person's groups intersected with the grant's groups
   (empty by default).

## Deliverable

- **Hardened token verification** (`app/security/oidc.py`). Beyond issuer, audience, expiry, signature, and key ID, the verifier now
  rejects: a subject that is empty or not a string; a tenant that is empty or not a string; **two tenant claims that disagree**
  (`tid` and `tenant_id`; previously one silently won); `purposes` or `groups` that are not a list of non-empty strings (a string
  used to be split into characters); and a malformed actor claim (RFC 8693 `act`: one level only, string `sub`, no chain, no extra
  fields). A valid actor is carried as the identity claim `act_sub`.
- **Identity resolution** (`app/security/identity.py`, `IdentityResolver`): verifies the token, then (a) if a directory is
  configured the person must exist and be active, and the effective groups are the token's groups **intersected with the directory's
  current groups**, so a removed group or a disabled person takes effect on the very next request and a group added after the token
  was issued is never granted by it; (b) if the token names an acting party, the delegation policy must be *approved* and grant that
  agent, and the effective purposes and groups are the intersection of the person's and the grant's.
- **Delegation policy contract** (`packages/platform_contracts/delegation.py`): `DelegationPolicy` of `AgentGrant`s (agent ID,
  purposes, groups, optional tenant list), with an approval block. The shipped policy
  (`services/analytics-api/delegation/delegation-policy.proposed.json`) is **`proposed`, so no delegated token is honoured until the
  user approves one**.
- `caller_kind` and the delegation claim names moved to `app/security/identity.py` (re-exported from `app.agent_tools`), so REST and
  tools share one definition. `V2Runtime` gained an optional `resolver`; without it nothing changes.
- `tests/idp_negative_suite.py`: 30 issuer-agnostic negative cases (mint a token, give the verifier its keys); only the local issuer
  is provided.

## Evidence

- `tests/test_ads063_identity.py` (45 tests, of which 30 are the parametrized negative suite): none of the 30 hostile tokens (expired,
  not yet valid, wrong issuer, wrong audience, missing or empty subject/tenant, disagreeing tenant claims, unsigned `alg: none`, wrong
  signature, tampered payload, unknown/missing key ID, malformed purposes/groups, malformed or chained actor claims) yields an
  identity; an RS256 verifier rejects the HS256-with-the-public-key confusion attack and a token signed by the wrong private key; a
  retired key stops working after rotation; a removed group is gone on the next request with the same token and changes an
  authorization decision for confidential data from allow to review; a group added later is not granted by an old token; a token
  cannot claim a group the directory does not grant; a disabled or unknown person, or the same name in another tenant, is refused;
  delegated calls get only the intersection of person and grant and are agents; delegation is refused without an approved policy, for
  an ungranted agent, or outside a grant's tenants; the shipped policy is valid and not approved; over REST, expired and malformed
  tokens are 401 and a disabled person is refused on the next request; a delegated token cannot review on REST or through the tool
  surface and the run does not move, while a human reviewer can; and the default reference runtime is unchanged.
- **The suite found real defects in the previous verifier.** Run against the unchanged verifier, **12 of the 30 hostile tokens were
  accepted**: an empty subject; a numeric tenant; **two disagreeing tenant claims (the token for `tid: tenant-a` with
  `tenant_id: tenant-b` was treated as tenant-b)**; `purposes` as a string (split into characters), with a non-string item, as an
  object, or with an empty entry; and five malformed actor claims (silently ignored). All are now rejected.

## Proposed policy (NOT APPROVED)

`services/analytics-api/delegation/delegation-policy.proposed.json`: one example grant (`agent-planner`: purpose `analytics`, no
groups, any tenant), status `proposed`. Delegation stays off until the user approves a policy. This is not the M6
`security_and_operations_review`.

## Boundary

- **No live identity provider.** Every token comes from the local test issuer (HS256, plus a generated RSA pair for the algorithm
  confusion test). The acceptance line "real IdP negative suite" is **not met**: the suite is ready to be pointed at a live provider,
  but that needs the user's explicit authorization and provider details, and it is not wired.
- The directory is an in-memory stand-in. Real group sources (SCIM, an IdP groups endpoint, a cache with a TTL) are not built; a
  production directory would add latency and a staleness window that this packet's "next request" guarantee assumes away.
- The resolver is mounted only where a runtime sets `V2Runtime.resolver`; nothing configures it in `app.main`.
- Group removal revokes access to *new* requests. A run already paused or executing keeps the identity it started with, and sealed
  evidence is not rewritten.
- Delegation chains (an agent acting for an agent) are refused rather than modelled.
- Token revocation lists, DPoP or mTLS binding, and refresh handling are not included.
