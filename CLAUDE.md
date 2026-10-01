# Claude Code Repository Guide

## Start Here

Before changing files, inspect `git status -sb`, the current branch, and recent
commits. This repository may contain user work; never discard or overwrite
unrelated changes. Follow the active packet's acceptance criteria and inspect
the implementation and tests before deciding what to change.

For project state and the current workstream, read
[`docs/handoffs/CLAUDE_CODE_HANDOFF.md`](docs/handoffs/CLAUDE_CODE_HANDOFF.md).
Canonical architecture and plans:

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/AGENTIC_DATA_STACK_EXECUTION_PLAN.md`](docs/AGENTIC_DATA_STACK_EXECUTION_PLAN.md)
- [`docs/execution/enterprise-analytics/README.md`](docs/execution/enterprise-analytics/README.md)
- [`docs/execution/enterprise-analytics/agentic-data-stack-program.yaml`](docs/execution/enterprise-analytics/agentic-data-stack-program.yaml)
- [`docs/ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md`](docs/ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md)
- [`docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`](docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md)

## Product Boundaries

- This is one monorepo with separate products and deployables: Resolution
  Intelligence/support and Analytics/Agentic Data Stack. Shared contracts live
  in `packages/platform_contracts`; do not put analytics domain code in the
  support API.
- The analytics product is under `services/analytics-api` and
  `apps/analytics-web`. Its governed runtime is the typed, durable graph runner
  in `services/analytics-api/app/runtime`, not the support API's LangGraph
  runtime. The Analytics graph-v2 uses explicit node and edge allowlists.
- PostgreSQL is the first customer-shaped analytical execution target;
  DuckDB is the embedded local/data-lake target. OpenSearch is the target
  enterprise context/search plane. Qdrant remains in legacy/general RAG paths;
  do not present it as the enterprise-search authority.
- Semantic definitions are Git-backed. Never claim a contract is certified
  just because code or a fixture refers to it; preserve the human semantic
  certification gate.

## Safety and Workflow

- Do not deploy to Azure, mutate cloud resources, connect to a live warehouse,
  or perform live OpenSearch validation unless the user explicitly asks for
  that action in the current task. Local fake-provider verification is the
  default.
- Human gates (semantic certification, security, policy, thresholds, and final
  go/no-go) require the user's explicit approval. Record approvals in the
  program manifest; never infer approval from implementation or tests.
- The user prefers milestone-sized commits pushed after each completed
  milestone. Verify branch/upstream and staged scope first; do not push partial
  work or unrelated changes.
- The user often asks for bounded implementation packets to be executed with
  a cost-efficient model such as Luna, reserving stronger models and human
  review for architecture, security, and consequential gates. Keep packets
  explicit about acceptance criteria, evidence, and decisions requiring a
  human; never fabricate model or reviewer approvals.
- Avoid compatibility scaffolding for hypothetical customers, per the user's
  direction that there are no customers yet. Still preserve established,
  pinned graph-v1 fixtures unless a task explicitly calls for their migration.
- Keep code, packet, roadmap, and diagrams synchronized when a milestone
  changes architecture. Do not claim an evaluation passed unless it was run.

## Useful Commands

```bash
make test-analytics
cd services/analytics-api && PYTHONPATH=.:../.. pytest tests/test_ads039_graph_adversarial.py -q
ruff check <changed-python-files>
ruff format --check <changed-python-files>
git diff --check
```

Check the current task's packet for the right scope and gates before running
broader commands. Do not auto-fix repository-wide lint findings outside the
task's ownership.
