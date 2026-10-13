# ADS-074: Security, Tenant-Isolation, and Policy Adversarial Evaluation

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. This is a test matrix over a local reference stack, **not an independent security review**; zero violations here is not a statement that none exist.

24 hostile probes (REST and agent tools), the 31-case ADS-067 corpus, and 48 protected-case runs from the ADS-070 corpus.

## Metrics

| Metric | Measured | Gate | Meets | Plan gate |
|---|---:|---:|:---:|---|
| `cross_tenant_leaks` | 0 | <= 0 | yes | Policy and tenant-isolation violations 0 |
| `purpose_violations` | 0 | <= 0 | yes | Policy and tenant-isolation violations 0 (a purpose the caller lacks) |
| `separation_of_duties_violations` | 0 | <= 0 | yes | A requester or an agent decides a review: 0 |
| `unauthenticated_successes` | 0 | <= 0 | yes | Forged, expired, wrong-audience, or missing tokens that succeed: 0 |
| `probe_agreement` | 1 | >= 1.0 | yes | Every hostile probe is refused without leaking the victim's data |
| `security_corpus_gates_met` | 1 | >= 1.0 | yes | ADS-067 security corpus gates met |
| `protected_case_failures` | 0 | <= 0 | yes | ADS-070 policy-denied, tenant-isolation, and refusal cases that fail: 0 |

## Probes

| Group | Surface | Probe | Refused | Leaked |
|---|---|---|:---:|:---:|
| cross_tenant | rest | read a run of another tenant | yes | no |
| cross_tenant | rest | feedback on a run of another tenant | yes | no |
| cross_tenant | rest | clarify a run of another tenant | yes | no |
| cross_tenant | rest | decide a review of another tenant | yes | no |
| cross_tenant | rest | re-submit the same idempotency key as another tenant | yes | no |
| purpose | rest | read a run under a purpose the caller lacks | yes | no |
| purpose | rest | read a run under a different purpose than it was made with | yes | no |
| purpose | rest | analyze under a purpose the caller lacks | yes | no |
| duties | rest | the requester approves their own review | yes | no |
| duties | rest | an automated caller approves a review | yes | no |
| duties | rest | approve with a stale plan fingerprint | yes | no |
| auth | rest | forged signature token reads a run | yes | no |
| auth | rest | forged signature token asks a question | yes | no |
| auth | rest | expired token reads a run | yes | no |
| auth | rest | expired token asks a question | yes | no |
| auth | rest | wrong audience token reads a run | yes | no |
| auth | rest | wrong audience token asks a question | yes | no |
| auth | rest | wrong issuer token reads a run | yes | no |
| auth | rest | wrong issuer token asks a question | yes | no |
| auth | rest | no token reads a run | yes | no |
| auth | rest | malformed bearer token | yes | no |
| cross_tenant | tools | analytics.status on a run of another tenant | yes | no |
| cross_tenant | tools | analytics.evidence on a run of another tenant | yes | no |
| duties | tools | a delegated agent decides a review | yes | no |

## Open security findings (not resolved)

- F-02: Run IDs were a plain hash of tenant, user, purpose, and a client-chosen key, so a colleague could compute and read another person's run
- F-03: Small cohorts and exact differencing: aggregates can reveal individual values
- F-05: Any caller in the same tenant with the run's purpose and the run ID can read its status and evidence

## Not measured

- **independent_security_review**: required by the plan before any pilot; this matrix is not one
- **live_identity_provider**: tokens are signed by a local issuer; a real IdP's behaviour (key rotation, group claims, token exchange) is not exercised
- **automated_actor_naming**: a caller is treated as automated only if its user id has a known prefix (system:, model:, agent:, service:) or carries a delegation claim; an automated actor with an ordinary-looking id would be treated as a human reviewer. Identity-provider configuration must enforce the convention.
- **network_and_infrastructure**: no network boundary, storage encryption, or deployment isolation is tested
- **data_plane_boundary**: the VPC simulator (ADS-064) is covered by its own tests, not this matrix
