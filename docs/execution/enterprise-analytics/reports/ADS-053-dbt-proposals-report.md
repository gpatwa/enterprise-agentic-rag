# ADS-053: dbt Change Proposal Report

Generated 2026-10-10 06:30 UTC by `make analytics-dbt-eval`. Corpus `dbt-corpus-v1` (`19f59008d742`), rules `dbt-proposal-rules-v1`.

**Result: MEETS the approved thresholds.** The thresholds were approved by user on 2026-10-09 (scope: these dbt-corpus thresholds only). This is not a gate pass for any human gate and approves no proposal.

## Scope and limits

- Proposals are inert data (status `proposed`) against a small fixture dbt project; nothing is applied and dbt is never run.
- The validation commands are text for a reviewer. Expectations were written by hand from the rule definitions on the fakes-only reference stack; they say nothing about whether the edits are good fixes.

## Metrics against approved thresholds

| Metric | Measured | Gate | Meets |
|---|---:|---:|:---:|
| `proposal_agreement` | 1 | >= 1.0 | yes |
| `provenance_completeness` | 1 | >= 1.0 | yes |
| `file_constraint_violations` | 0 | <= 0 | yes |
| `validation_command_coverage` | 1 | >= 1.0 | yes |
| `commands_executed` | 0 | <= 0 | yes |
| `source_file_writes` | 0 | <= 0 | yes |
| `edit_validity` | 1 | >= 1.0 | yes |
| `determinism` | 1 | >= 1.0 | yes |
| `dedupe_agreement` | 1 | >= 1.0 | yes |

## Cases

| Case | Scenario | Expected | Got | Result |
|---|---|---|---|:---:|
| Q01 | answer | {'operation': 'add_column_description', 'target_id': 'sales_orders.amount'} | {'operation': 'add_column_description', 'target_id': 'sales_orders.amount'} | pass |
| Q02 | answer | {'operation': 'add_column_description', 'target_id': 'sales_orders.amount'} | {'operation': 'add_column_description', 'target_id': 'sales_orders.amount'} | pass |
| Q03 | answer_omit_status | {'operation': 'add_column_description', 'target_id': 'sales_orders.status'} | {'operation': 'add_column_description', 'target_id': 'sales_orders.status'} | pass |
| Q04 | answer | {'none': 'column_already_described'} | {'none': 'column_already_described'} | pass |
| Q05 | policy_denied | {'none': 'category_not_applicable'} | {'none': 'category_not_applicable'} | pass |
| Q06 | answer | {'none': 'claim_only'} | {'none': 'claim_only'} | pass |
| Q07 | answer | {'none': 'model_not_found_in_approved_files'} | {'none': 'model_not_found_in_approved_files'} | pass |
| Q08 | answer | {'operation': 'add_column_description', 'target_id': 'sales_orders.amount'} | {'operation': 'add_column_description', 'target_id': 'sales_orders.amount'} | pass |
| Q09 | answer | {'none': 'category_not_applicable'} | {'none': 'category_not_applicable'} | pass |

## Proposals generated

- `9029c3c79870` add_column_description on `sales_orders.amount` in `models/sales/schema.yml` (commands: `dbt parse`, `dbt test --select sales_orders`)
- `0e8ccab01fab` add_column_description on `sales_orders.status` in `models/sales/schema.yml` (commands: `dbt parse`, `dbt test --select sales_orders`)

## Not measured

- **dbt_validation**: dbt is never run here; the validation commands are text for a reviewer
- **proposal_usefulness**: needs reviewers and real feedback; reviewing proposals is ADS-055
