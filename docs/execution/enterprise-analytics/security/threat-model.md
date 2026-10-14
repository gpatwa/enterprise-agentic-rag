# Threat model: governed analytics (ADS-067)

Status: **Review** (written by the implementing agent; **not** an independent security review). Severities are the implementing agent's ratings; accepting a residual risk is the security owner's decision.

## Scope, assets, and actors

**Assets:** the customer's warehouse data and credentials; tenant isolation; the certified semantic contracts and ontology; evidence and audit records; the learning loop's protected files (goldens, thresholds, policies); platform availability and cost.

**Actors:** an authorized analyst; a malicious or compromised analyst; a colleague in the same tenant; another tenant; a hijacked or prompt-injected model; an AI agent calling tools or MCP; a compromised reviewer; an operator with schema rights; a network attacker on the control/data-plane channel.

## Trust boundaries

```text
client / MCP caller  -->  API + tool surface  -->  governed graph  -->  compiler  -->  gateway  -->  warehouse
      (token)              (identity, quotas)     (model output untrusted)  (deterministic)  (read-only)    (customer)
                                   |                        |                                   |
                                evidence store (append-only)  telemetry (redacted)     data plane (rows stay inside)
```

1. **Caller to service:** everything from a caller (request text, arguments, tokens) is untrusted until verified.
2. **Service to model:** model output is untrusted data; it is validated and re-resolved, never executed.
3. **Control plane to data plane:** only metadata and verdicts cross; rows and credentials do not.
4. **Learning loop to production:** feedback can propose, never apply; promotion needs separate human approvals and an evaluation.

## Threats and controls

Each row's **Verification** column lists `test file::test name` pairs; `test_ads067_security.py` checks that every one of them exists, so this table cannot silently go stale.

| ID | Component | Threat | Controls | Verification | Residual risk |
|---|---|---|---|---|---|
| T-01 | Request text / model | Prompt injection: request or retrieved context instructs the model to run arbitrary SQL, change scope, or reveal data | The model only returns a strict, schema-validated `AnalyticalIntent` (no SQL field, extra fields rejected); every ID must be a certified semantic ID; SQL is compiled deterministically from the intent and never authored by a model; filter values are bound parameters | `tests/test_ads067_security.py::test_the_hostile_model_and_injection_cases_run_nothing` ; `tests/test_ads040_execution_gateways.py::test_unsafe_sql_is_rejected` | The corpus simulates a hijacked model by replacing its output. Resistance of a real model is not measured; the controls do not depend on it |
| T-02 | Model output | A hijacked model targets another tenant, an uncertified metric, or an unknown dataset | Intent identity, certification, and ontology resolution are checked after the model; cross-tenant scope fails before retrieval | `tests/test_ads067_security.py::test_the_hostile_model_and_injection_cases_run_nothing` | None known |
| T-03 | Explanation | A hijacked explainer fabricates numbers or cites ids it was not given | Claims are accepted only if every number comes from a cited cell and every citation exists; otherwise the answer degrades to evidence only; the result cannot change | `tests/test_ads043_grounded_explanation.py::test_a_number_must_come_from_a_cited_cell_not_just_any_cell` ; `tests/test_ads067_security.py::test_the_hostile_explainer_cases_degrade_to_evidence_only` | Prose meaning (for example 'highest') is not verified |
| T-04 | Prompt | Request text breaks out of the data block of the intent prompt | The request is embedded as one JSON string after an explicit untrusted-data instruction | `tests/test_ads067_security.py::test_request_text_cannot_break_out_of_the_prompts_data_block` | A real model may still be steered; T-01 controls limit the damage |
| T-05 | Identity | Forged, expired, mis-scoped, or malformed tokens; algorithm confusion; key rotation | Strict claim validation, pinned algorithms and keys, per-request resolution against a directory; 30-case negative suite (12 were accepted by the previous verifier) | `tests/test_ads063_identity.py::test_malformed_or_untrusted_tokens_never_yield_an_identity` ; `tests/test_ads061_mcp.py::test_every_message_needs_a_valid_token_and_changes_in_the_directory_apply_to_the_next_message` | Only the local test issuer is exercised; a real identity provider is not |
| T-06 | Identity | A removed group or disabled person keeps access until the token expires | Groups are intersected with the directory on every request | `tests/test_ads063_identity.py::test_a_removed_group_takes_effect_on_the_next_request_not_at_token_expiry` | A real directory adds a staleness window |
| T-07 | Delegation | An agent acting for a person exceeds the person's or its own authority, or approves a review | Delegation needs an approved policy; effective purposes and groups are the intersection; agent and delegated callers can never decide a review (REST, tools, MCP) | `tests/test_ads063_identity.py::test_delegation_is_refused_unless_the_policy_is_approved_and_grants_that_agent` ; `tests/test_ads060_agent_tools.py::test_agents_and_delegated_callers_can_never_decide_a_review` | The shipped delegation policy is proposed, so delegation is off |
| T-08 | Tenancy | One tenant reads another tenant's run, evidence, or artifact | Every read is scoped by tenant and purpose; cross-tenant lookups return not-found | `tests/test_ads067_security.py::test_another_tenants_reads_return_not_found` ; `tests/test_ads045_analyze_api.py::test_status_is_tenant_and_purpose_scoped` | Same-tenant colleagues holding a run ID can read it (F-05, accepted by design) |
| T-09 | Run IDs | A colleague computes another person's run ID from their user ID and a guessable idempotency key | With `run_id_key` the ID is an HMAC | `tests/test_ads067_security.py::test_a_server_key_makes_run_ids_underivable` | Deployments must set the key (F-02); the default is derivable |
| T-10 | Compiler / gateway | SQL injection or write/DDL reaches the warehouse | Compiled SQL is parameterized; the gateway re-validates read-only, allow-listed tables and functions, and the engine locks external access | `tests/test_ads040_execution_gateways.py::test_engine_level_isolation_holds_even_if_validation_were_bypassed` ; `tests/test_ads040_execution_gateways.py::test_postgres_runs_in_read_only_transaction_with_timeouts_and_always_rolls_back` | PostgreSQL was exercised only against a fake engine |
| T-11 | Gateway | Runaway queries or oversized results exhaust the warehouse | Timeout, cancellation, row, byte, and cost limits; admission quotas per tenant | `tests/test_ads040_execution_gateways.py::test_cost_limit_blocks_before_execution` ; `tests/test_ads066_quotas.py::test_a_denial_of_wallet_stops_at_the_budget_and_other_tenants_keep_their_own` | Cost units are uncalibrated against money |
| T-12 | Result | A wrong result (fanout, missing groups, truncation) is explained as fact | Result validation with an independent control query before any explanation | `tests/test_ads041_result_validation.py::test_join_fanout_is_detected` ; `tests/test_ads041_result_validation.py::test_truncation_is_blocking_and_skips_reconciliation` | A bug shared by the primary and control queries would not be caught |
| T-13 | Time | A time range selects different data depending on the server's time zone | Both gateways pin the session time zone to UTC | `tests/test_ads067_security.py::test_the_session_time_zone_is_pinned_to_utc` | None known |
| T-14 | Inference | Aggregates reveal individual rows: one-row groups, filters on the entity key, small cohorts, exact differencing | Unbucketed temporal grouping and grain-key grouping are refused; optional minimum cohort suppresses small groups and refuses filters on the entity key | `tests/test_ads067_security.py::test_the_compiler_refuses_row_level_groupings` ; `tests/test_ads067_security.py::test_the_minimum_cohort_is_validated_and_suppression_is_a_warning_not_a_failure` | Differencing across two large cohorts remains possible and `min_cohort` is off by default (F-03: a data-owner decision) |
| T-15 | Data plane | Rows or warehouse credentials cross to the control plane, or the channel is forged or replayed | Messages cannot carry rows or credentials; signed, fresh, replay-proof envelopes; rows go only to the requester from the data plane | `tests/test_ads064_data_plane.py::test_a_row_leaking_agent_is_blocked_and_recorded` ; `tests/test_ads064_data_plane.py::test_unsigned_forged_tampered_stale_and_replayed_messages_are_refused` ; `tests/test_ads064_data_plane.py::test_rows_are_released_only_to_the_requesting_person_with_their_own_valid_token` | A simulator, not network isolation; the shared channel key is symmetric |
| T-16 | Evidence | Evidence is rewritten, deleted, or forged | Append-only hash-chained store with database triggers and chain verification | `tests/test_ads042_evidence_envelope.py::test_store_rejects_mutation_and_verification_detects_tampering` ; `tests/test_ads062_artifact.py::test_any_change_to_a_stored_artifact_is_rejected` | Rewriting the whole chain is not detected; chain heads are not anchored or signed |
| T-17 | Telemetry | Logs, traces, or metrics leak requests, tokens, SQL, or values | Allow-listed attributes and labels, redaction, run references instead of IDs | `tests/test_ads065_observability.py::test_no_question_token_run_id_sql_row_value_or_physical_name_is_ever_exported` | Redaction is pattern-based behind the allow-lists |
| T-18 | Audit | Tool calls on some transport go unrecorded or record data | One audit in the tool surface for every transport, argument digests only | `tests/test_ads061_mcp.py::test_every_call_is_audited_without_argument_values_tokens_or_data` | The audit chain is in memory |
| T-19 | Learning loop | Malicious feedback changes goldens, policy, or production behaviour; self-approval; a compromised reviewer | Strict feedback, triage that ignores free text, proposals that cannot certify, separation of duties, an evaluation gate and an approved rollout policy | `tests/test_ads059_poisoning.py::test_every_attack_class_is_blocked_and_nothing_protected_moved` ; `tests/test_ads059_poisoning.py::test_a_compromised_reviewer_is_stopped_by_the_evaluation_gate_not_by_the_review` ; `tests/test_ads055_review.py::test_forbidden_reviewers_are_refused_and_leave_no_decision` | Collusion between two real reviewers is not covered |
| T-20 | Availability | A noisy tenant starves others | Per-tenant rate, concurrency, and cost quotas | `tests/test_ads066_quotas.py::test_a_noisy_neighbour_is_throttled_without_touching_another_tenants_service` | State is in memory and per replica |
| T-21 | Tool surface | A caller smuggles identity or unknown arguments through a tool call | Strict argument models reject unknown fields; identity comes only from the transport's token | `tests/test_ads061_mcp.py::test_identity_can_never_come_from_the_arguments` ; `tests/test_ads060_agent_tools.py::test_invalid_arguments_are_rejected_without_echoing_them` | None known |
| T-22 | Prompt registry | A candidate prompt weakens the defensive clauses | The contract requires the baseline's defensive clauses | `tests/test_ads054_prompt_registry.py::test_a_prompt_that_drops_a_defensive_clause_is_rejected` | The runtime does not read the registry yet |

## Findings register

The findings register (F-01 to F-06), their severities, statuses, and evidence live in `services/analytics-api/reference_stack/security/security-corpus-v1.json` and are rendered in `reports/ADS-067-security-report.md` by `make analytics-security-eval`.

## Decisions that belong to people

- **Minimum cohort (F-03):** whether to enable `min_cohort`, and its value per dataset, depends on what the data is. Personal or restricted data should not be onboarded until the data owner and security owner decide this and whether per-person query auditing is required.
- **Run ID key (F-02):** a deployment checklist item; a deployment without `run_id_key` keeps derivable run IDs.
- **Same-tenant run reads (F-05):** whether to restrict reads to the requester and reviewers.
- **Accepting any residual risk above, and the M6 `security_and_operations_review`.**

## Not covered

Real-model injection resistance, novel attacks, side channels (timing, caches), supply chain, infrastructure and secrets management, a real identity provider, and a penetration test.
