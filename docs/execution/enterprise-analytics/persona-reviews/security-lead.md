Status: AI persona advisory review (security lead). Not an approval, sign-off, or independent human review.

Reviewed at commit `27663d6` (branch `claude/persona-reviews`). Local evidence only: the five security suites
(`test_ads067_security`, `test_ads063_identity`, `test_ads061_mcp`, `test_ads064_data_plane`, `test_ads074_isolation`) pass
(96 passed), and one local probe against the DuckDB reference stack (fakes only) confirmed findings C-01 and C-04 below. No network,
IdP, warehouse, or cloud service was used. Nothing in this review changes a threshold, policy, or the program manifest.

## Summary

The deterministic core is solid. The model cannot author SQL. Identifiers are quoted and values are bound. Tokens are strictly
validated, cross-tenant reads return not-found, and the data plane fails closed. I found no SQL injection and no cross-tenant leak.

The weak area is **authorization inside a tenant**, and it is weaker than the findings register says:

- **Run reviews need no reviewer role (C-01, high).** Any human in the same tenant and purpose, other than the requester, can
  approve a paused run. I confirmed this locally: a colleague with no groups approved a review, and the run completed.
- **F-05 is understated (C-04).** A same-tenant reader gets the full result rows (not only status and evidence), and those rows
  were computed under the requester's groups. A colleague holding a run ID can read data they could not query themselves.
- **Classification checks are coarse (C-02, C-03).** Belonging to any group at all skips the confidential and restricted review,
  and field-level classification is never enforced in the governed path.
- **The app shell has unsafe defaults (C-05).** The API-key check fails open, the legacy v1 NL-to-SQL endpoint is mounted, and
  `/health` returns raw exception text.

**Recommendation: no-go for a pilot today. Go for a limited pilot once the conditions in "Pilot view" are met.** Most of the
conditions are small code changes plus deployment configuration.

## Findings decisions (F-02, F-03, F-05)

### F-02: derivable run IDs (`run_id_key`): **Resolve** (fail closed)

The HMAC in `analyze_service.py:131-141` is correct, but it is optional. With no key the ID is derivable
(`analyze_service.py:138-139`), and nothing enforces a key at startup. Because of C-04, a derivable ID is a direct read of another
person's result rows. Resolve it this way:

1. `GovernedAnalyzeService` refuses to construct without `run_id_key` unless an explicit test or local flag is set. The production
   app factory (or `ENV=prod`) must never pass that flag.
2. The key comes from the secret manager, is at least 32 random bytes, is never logged, and is listed in the ADS-069 runbook.
   Rotating it orphans in-flight idempotency keys; that is acceptable, so document "rotate between pilot waves".
3. Keep `derive_run_id` for tests only. Production telemetry and quotas already use `run_id_for`
   (`observability/instrumentation.py:66`, `quotas/guard.py:70`).
4. Optional hardening: the requester tag that prefixes `query_id` is an unkeyed `sha256(user_id)[:16]`
   (`analyze_service.py:107,247,401-402`). Key it the same way so a reader cannot link a run to a person by dictionary.

### F-03: small cohorts and differencing (`min_cohort`): **Accept for the pilot only with compensating controls; start at k = 10**

The control has limits that are not in the register:

- It counts rows, not entities: `HAVING COUNT(*) >= k` (`compiler/postgres.py:103-104`). On a transaction-grain dataset, one
  customer with 10 orders passes k = 10.
- It refuses filters only on the metric's grain key (`postgres.py:74-76`). A filter on another quasi-identifier (customer, email,
  store) is allowed, and so are `not_equals` and `not_in` (`analytics_intent.py:51-60`). That makes "total minus everyone except X"
  differencing straightforward.
- There is no complementary suppression. An ungrouped total minus the visible groups reveals a single suppressed group, and
  nothing correlates a person's queries (register: `query_auditing` not built).

**Starting value: `min_cohort = 10`** for every pilot dataset, on both the compiler and the data-plane agent. Reasoning:

- k = 5 is the common floor, but because counting is per row (not per entity), the effective entity-level k can be much lower than
  the configured k. Starting at 10 gives margin.
- 10 still answers typical internal business questions (by month, region, or category) without heavy suppression.
- Values from about 11 to 20 (public-health-style rules) are only worth it for personal data. Personal data should not be in this
  pilot anyway.
- Re-run the ADS-070/071 correctness corpus with k = 10. Today the corpus runs with `min_cohort` off, so the effect on answer rate
  is unmeasured.

Compensating controls required for this acceptance:

1. Onboard only datasets the data owner attests contain no personal, restricted, or HR/compensation data. Personal data waits for
   the follow-ups below.
2. Enable `min_cohort=10` in the compiler and in `DataPlaneAgent(min_cohort=...)`.
3. Keep a per-person query log for the pilot: identity, time, and intent fingerprint (metrics, dimensions, filter field IDs), with
   retention. Review it weekly. Today the tool audit stores only an unsalted argument digest (`agent_tools/audit.py:22-27,48`), which
   cannot answer "what did this person ask".
4. Use a small, named pilot cohort of users.

Follow-ups before any personal data is onboarded:

- Count distinct entity keys in the cohort check: `COUNT(DISTINCT <entity key>)`, where the entity key is declared in the contract.
- Refuse `not_equals` and `not_in` on quasi-identifier fields when `min_cohort` is on.
- Suppress complementary groups (or round) when exactly one group is withheld.
- Build per-person differencing detection.

### F-05: same-tenant readers: **Resolve, do not accept**

The register says "status and evidence". In code, `status()` returns the full answer table to any same-tenant, same-purpose caller
(`analyze_service.py:150-152`, rows assembled at `:285-307` and `:360-364`). Those rows were produced under the requester's
groups and policy decision. That is an authorization bypass for any reader with fewer groups, not just a confidentiality nit. I
confirmed it locally: a groupless third user read `rows: [['5050']]` of another user's run. Resolve it this way:

1. Bind `status`, `evidence` (`agent_tools/dispatcher.py:112-124`), and feedback to the requester, using the same tag check that
   `clarify` already does (`analyze_service.py:159-160`).
2. Allow a reviewer to read the run only while the review is pending and only as the review view (plan fingerprint, reasons), never
   the rows. This keeps the "reviewers can open a paused run" use case that motivated the acceptance.
3. If sharing results is a product need later, re-authorize the reader against the run's policy decision (groups and
   classification) before returning rows. Treat it as an explicit share, not as possession of an ID.
4. Return `run_not_found` (404) for non-requesters so run IDs cannot be probed.

## Threshold and policy recommendations

| File | Recommendation | Values | Reason |
|---|---|---|---|
| `reference_stack/security/security-thresholds.proposed.json` | **Amend, then approve** | Keep all seven gates and values (`control_agreement >= 1.0`, `documented_gap_agreement >= 1.0`, the five `<= 0` gates). Amend `unresolved_critical_high_findings` so it counts the **security owner's** severity, not the implementing agent's "pilot scope" downgrade. Add corpus control cases for C-01 (a non-reviewer approves → refused), C-02 (an unrelated group on confidential data → review), and F-05 (a colleague reads rows → not found), so `control_agreement` covers them. | The values are correct, since zero tolerance is right for these gates. But the high/critical gate passes partly because F-03 was rated down by its author, and the corpus has no case for the intra-tenant authorization gaps found here. Bump `corpus_sha256` when the cases are added. |
| `reference_stack/m7/isolation-thresholds.proposed.json` | **Amend, then approve** | Keep all seven gates (`cross_tenant_leaks`, `purpose_violations`, `separation_of_duties_violations`, `unauthenticated_successes` `<= 0`; `probe_agreement`, `security_corpus_gates_met` `>= 1.0`; `protected_case_failures <= 0`). Add `same_tenant_overreach <= 0`, covering a non-requester reading rows, a non-reviewer approving, and an unrelated group unlocking confidential data. Add a non-reviewer approval probe to `separation_of_duties_violations`. | Today the matrix reports 0 SoD violations while any colleague can approve (C-01). The probes test only the requester and agents (`isolation_eval.py:235-262`), so the gate cannot fail on the real gap. |
| `delegation/delegation-policy.proposed.json` | **Do not approve for the pilot** (keep `proposed`, so delegation stays off). If an agent use case is required, amend before approval. | `{"agent_id": "<IdP client ID of the agent, not a free label>", "purposes": ["analytics"], "groups": [], "tenants": ["<pilot tenant id>"]}`, plus an `approval.note` stating owner and review date. | `tenants: []` means every tenant (`platform_contracts/delegation.py:33,56`); a pilot grant should be explicit. `groups: []` is correct (no confidential reach). The contract has no expiry, so the review date must be procedural. Approval integrity rests on Git review, because the validator only checks that `approved_by` and `approved_at` are non-empty (`delegation.py:46-47`). Put the file under CODEOWNERS. The tool audit does not record the acting agent (C-08), so delegated actions would not be attributable. |
| `min_cohort` (deployment configuration, no file yet) | **Set** | `10` on the compiler and the data-plane agent for all pilot datasets | See F-03. |
| `run_id_key` (deployment configuration) | **Require** | At least 32 random bytes from the secret manager, with startup failing without it | See F-02. |

## Code review findings

| ID | Severity | File:line | Issue | Fix |
|---|---|---|---|---|
| C-01 | **High** | `app/runtime/control_store.py:314-370`; `app/api_v2.py:91-92`; `app/agent_tools/dispatcher.py:74-75` | Run review approval checks only tenant, purpose, human-ness, requester ≠ reviewer, and fingerprint. There is **no reviewer role**: `REVIEWER_GROUP` ("analytics-reviewer") is enforced only in the learning-loop rules (`app/review/rules.py:52`). Any colleague can approve a policy review (`governed_stages.py:309-342`) or a cost review. Confirmed locally: a user with `groups=()` approved and the run went terminal. | In `resolve_review`, require `REVIEWER_GROUP` (or a per-policy approver group from the contract), checked against the directory-resolved groups. Add an ADS-074 probe. |
| C-02 | **Medium-High** | `app/security/authorization.py:29-33` | Confidential and restricted policies need review only when `not identity.groups`, so **any** group (for example "analyst") skips review. Restricted data is never denied, only reviewed, and C-01 makes that review approvable by anyone. This is inconsistent with `data_access.py:18-21`, which requires the specific `restricted-data` and `confidential-data` groups. | Map each classification to a required group. Deny restricted without `restricted-data`. Review (or deny) confidential without `confidential-data`. Better still, let `SemanticPolicy` name its allowed groups. |
| C-03 | Medium | `app/security/data_access.py:8-22` (no caller outside tests); `packages/platform_contracts/analytics_intent.py:118-120` | `SemanticField.classification` is not enforced anywhere in the governed graph. An intent may filter on any contract field, so a `greater_than` binary search on a restricted field plus `COUNT` reveals attribute values even when the field is never selected. | Call `enforce_field_access` in `policy_node` (`governed_stages.py:285-295`) over measure, dimension, filter, and time-range fields, and include its decision in the evidence. |
| C-04 | Medium (it is F-05) | `app/runtime/analyze_service.py:150-152,285-307` | `status` returns full rows to any same-tenant, same-purpose caller with the run ID, computed under the requester's authorization. The response's `user_id` is the reader, not the requester (`:249`), which misattributes the answer. | See F-05. |
| C-05 | Medium | `app/main.py:48-53,96-119,77`; `app/analytics/engine.py:157-159`; `app/context/bootstrap.py:81` | Unsafe app-shell defaults. `verify_api_key` is a no-op when `ANALYTICS_API_KEY` is unset, and its comparison is not constant-time. The legacy `/api/v1/analytics/query` runs **LLM-generated SQL** with no identity or tenant scoping and returns the SQL and error text. Unauthenticated `/health` returns raw bootstrap exception text (`str(exc)`), which can contain hosts or URLs. The `ENV=prod` guard checks only CORS (`main.py:34-37`). | In prod, fail startup unless the API key, OIDC resolver with directory, and `run_id_key` are configured. Do not mount v1 in the pilot deployment. Use `hmac.compare_digest`. Return only a status code from `/health`. |
| C-06 | Medium (defence in depth) | `app/data_plane/agent.py:154-156,165,274-275`; `app/execution/result_validation.py:167` | The data plane executes the control plane's SQL and policy values as given. `min_cohort` there only blocks an *empty* result, so a compromised control plane (which can sign anything with the symmetric key, as ADS-064 notes) can drop `HAVING` or the row filters. | The data plane recompiles the plan from the certified intent and contract with its own compiler (it already holds `compilers`) and requires an identical fingerprint. It should also source identity-claim policy values itself. Move to asymmetric signing (ADS-064 follow-up). |
| C-07 | Low | `app/security/oidc.py:42`; `app/mcp/adapter.py:62-67` | A validly signed token whose `tid` or `tenant_id` is a list or object raises `TypeError` (unhashable) outside the `try`. Verified locally. REST answers 500 instead of 401, and `McpAdapter.handle` catches only `AuthenticationError`, so the exception escapes and ends `serve_lines`. Exploiting it needs a token from the trusted issuer. | Type-check both tenant claims as non-empty strings before building the set, and catch broadly in the adapter's auth step. |
| C-08 | Low | `app/agent_tools/audit.py:42-51,22-27` | The audit records `identity.user_id` only. For delegated calls the acting agent (`act_sub`) is lost, so agent actions are indistinguishable from the person's. The argument digest is unsalted SHA-256 of low-entropy values (purpose, run ID, short questions), so it is guessable. | Add `caller_kind` and `act_sub` to the payload. Use an HMAC with an audit key for the digests. |
| C-09 | Low | `app/security/oidc.py:59-67` | `act.client_id` is not type-checked, and `act.sub == sub` (self-delegation) is accepted. Currently harmless, because delegation is an intersection and marks the caller as an agent. | Require a string `client_id` if present, and reject `act.sub == sub`. |
| C-10 | Low | `app/data_plane/agent.py:181-194,233-241,251-255` | Expired result handles are removed only when fetched (unbounded memory), and the gateway cache never re-reads a rotated credential. | Sweep expired handles on each execute. Give the gateway cache a TTL. |
| C-11 | Info | `app/main.py:56`; `app/security/identity.py:94`; `app/review/rules.py:9-21`; `app/security/identity.py:67` vs `oidc.py:73` | No resolver or directory is wired in `app.main`, so group revocation and the disabled-user check depend on deployment wiring. Automated actors are detected only by user-ID prefix (already recorded). `caller_kind` checks `azp_agent` and `delegated_by`, but the verifier never passes them through, so only RFC 8693 `act` marks an agent. | Wire `IdentityResolver(directory=...)` in the pilot deployment. Configure the IdP so that service principals carry a prefixed subject or `act`. |

Checked and **none found**:

- SQL injection in the compiler. Identifiers are quoted (`postgres.py:251-253`). Values are bound (`:194-216`).
  `time_granularity`, `direction`, `target_kind`, and `limit` are `Literal` or `int`-bounded (`analytics_intent.py:33,73-75,91`).
  `min_cohort` is `int`-cast.
- Cross-tenant reads. Every control-store read is keyed by tenant and purpose (`control_store.py:325-351`;
  `analyze_service.py:219-225`), and the ADS-074 probes agree.
- Token verification weaknesses beyond C-07 and C-09. Algorithms are pinned and the `kid` must be known (`oidc.py:26-37`).
- Credentials or exception text crossing the data-plane boundary (`agent.py:113-116,228-231`).
- Telemetry carrying run IDs or values. Hashed `run_ref` is used and attributes are allow-listed.

## Pilot view

**Security position: no-go today. Conditional go for a limited internal pilot once all of the following hold.**

1. C-01 is fixed: run reviews require the reviewer group, with a matching probe in ADS-074.
2. F-05 / C-04 is fixed: rows go only to the requester, and reviewers get a rows-free review view.
3. F-02 is enforced fail-closed with a managed `run_id_key`.
4. C-02 is fixed, **or** the pilot datasets contain only `public` and `internal` policies and fields, attested by the data owner.
5. `min_cohort = 10` is enabled, there is no personal or restricted data, and a per-person query log is in place (F-03
   compensating controls).
6. The pilot deployment does not mount v1, makes the API key and OIDC resolver with directory mandatory, and sanitizes `/health`
   (C-05).
7. Delegation stays off (policy remains `proposed`).
8. The amended thresholds are approved by the user and recorded in the manifest, and the ADS-067 and ADS-074 evaluations are re-run
   with the new cases.
9. Before real users: the ADS-063 negative suite is run against the pilot IdP (needs explicit authorization), and an independent
   human security review or light penetration test is done. This persona review does not satisfy the plan's
   `independent_security_review` or the M6 `security_and_operations_review`.

C-06 to C-10 can follow the pilot start, provided the data plane is not deployed in the pilot or the control plane is operated by
the same trusted team.

## Questions for the human owner

1. Who should be able to approve a run review: a global `analytics-reviewer` group, or an approver group named per policy or
   dataset in the semantic contract?
2. Is there a real product need for colleagues to read each other's results? If so, should it be an explicit share that
   re-authorizes the reader, rather than possession of a run ID?
3. Which datasets are in the pilot, and will the data owner attest that none has personal, restricted, or compensation data? Is
   k = 10 acceptable for their typical questions (to be checked by re-running the correctness corpus with k = 10)?
4. Is the legacy v1 endpoint needed at all in the pilot deployment, or can it be removed from that app build?
5. Which IdP and directory will the pilot use, and do you authorize running the ADS-063 negative suite against it?
6. Is there any agent or MCP delegation use case in the pilot? If not, should delegation stay off until after it?
7. Who will perform the independent human security review, and what retention applies to the per-person query log?
