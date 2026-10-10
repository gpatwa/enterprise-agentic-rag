# Enterprise Search Task Packets

The canonical task list and dispatch rules are maintained in the
[Enterprise Search and Recommendation OpenSearch Execution Plan](../../ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md).

Use one task ID per delegated coding-model session. Create a dedicated packet
in this directory only when a task needs additional examples, fixtures, or
review notes beyond the canonical plan.

## Start Here

The first safe dispatch wave is:

| Task | Purpose | Can run concurrently |
|---|---|---|
| [OS-001](OS-001-opensearch-architecture-adr.md) | OpenSearch architecture ADR | Yes, with OS-005 |
| [OS-005](OS-005-search-golden-corpus.md) | Golden support-search corpus | Yes, with OS-001 |

Do not dispatch provider implementation until OS-001 has merged. Do not
dispatch the evaluation harness until the OS-005 corpus shape is stable.

## Packet Naming

Use `OS-NNN-short-description.md`. A packet must copy the task's dependencies,
owned files, acceptance evidence, targeted test command, and stop conditions
from the canonical plan.

## Integration Gate

```bash
PYTHONPATH="$PWD/services/api:$PWD" pytest services/api/tests -q
npm --prefix apps/support-web run typecheck
npm --prefix apps/support-web test -- --run
git diff --check
```
