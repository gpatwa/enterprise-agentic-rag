# ADS-054: Prompt and Example Registry Report

Generated 2026-10-10 07:05 UTC by `make analytics-prompts-eval`. Corpus `prompt-registry-corpus-v1` (`b048a2c371aa`), rules `prompt-registry-rules-v1`.

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. This is not a gate pass for any human gate and releases no prompt.

## Scope and limits

- The registry only records versions and refuses changes to released ones; nothing in the runtime reads it, and no candidate is promoted here.
- Expectations were written by hand on the fakes-only reference stack. They show immutability and isolation behave as specified, not that a candidate prompt is better.

## Metrics against proposed thresholds

| Metric | Measured | Gate | Meets |
|---|---:|---:|:---:|
| `outcome_agreement` | 1 | >= 1.0 | yes |
| `overwrite_rejection` | 1 | >= 1.0 | yes |
| `released_mutations` | 0 | <= 0 | yes |
| `candidate_namespace_violations` | 0 | <= 0 | yes |
| `example_text_leakage` | 0 | <= 0 | yes |
| `tenant_isolation` | 1 | >= 1.0 | yes |
| `determinism` | 1 | >= 1.0 | yes |
| `runtime_prompt_drift` | 0 | <= 0 | yes |
| `protected_file_writes` | 0 | <= 0 | yes |

## Cases

| Case | Operation | Expected | Got | Result |
|---|---|---|---|:---:|
| R01 | baseline_same | idempotent | idempotent | pass |
| R02 | baseline_changed | rejected | rejected | pass |
| R03 | candidate_valid | accepted | accepted | pass |
| R04 | candidate_valid | idempotent | idempotent | pass |
| R05 | candidate_identical_to_parent | rejected | rejected | pass |
| R06 | candidate_drops_untrusted_data_clause | rejected | rejected | pass |
| R07 | candidate_drops_certified_ids_clause | rejected | rejected | pass |
| R08 | candidate_drops_no_sql_clause | rejected | rejected | pass |
| R09 | candidate_wrong_placeholders | rejected | rejected | pass |
| R10 | candidate_unknown_parent | rejected | rejected | pass |
| R11 | candidate_without_baseline | rejected | rejected | pass |
| R12 | candidate_version_as_release | rejected | rejected | pass |
| R13 | example_ok | accepted | accepted | pass |
| R14 | example_without_correction | rejected | rejected | pass |
| R15 | example_unsafe_verdict | rejected | rejected | pass |
| R16 | other_tenant_reads_candidate | invisible | invisible | pass |
| R17 | other_tenant_reads_baseline | visible | visible | pass |

## Not measured

- **prompt_quality**: whether a candidate prompt improves answers needs evaluation against real data; that is ADS-056
