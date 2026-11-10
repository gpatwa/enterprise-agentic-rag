# agentic-resolution-intelligence

A LangGraph agent system that turns support tickets and knowledge into searchable resolution memory and evidence-backed answers, with reviewed agent commands.

## What is agentic here

**Agentic.** A LangGraph graph (`services/api/app/agents/graph.py`) with clarify, context-enricher, planner, retriever, tool, evaluator and responder nodes, plus reviewed agent commands. Model clients for several backends live in `services/api/app/clients`.

**Not claimed:** production use (it is not deployed) or answer quality (no live evaluation is recorded).

## Layout

`services/api`, `apps/support-web`, `pipelines`, `libs`, `models`, `eval`, `deploy`, the platform services (`control-plane`, `data-plane`, `gateway`, `sandbox`), `infra/terraform`.

## Test

```bash
cd services/api && PYTHONPATH=.:../.. python3 -m pytest tests/pipelines tests/test_tenant_data_isolation.py -q
```

## Status

Pilot stage. Nothing here is production, and no compliance certification is claimed. Cloud changes (Terraform apply,
deploys) are made only on the owner's explicit request. See `CLAUDE.md` for the working rules and
`docs/handoffs/CLAUDE_CODE_HANDOFF.md` for the current state.

## Related repositories

This repository was extracted from a monorepo with its history. The products are independent and import nothing from each other:

- `agentic-data-analytics`
- `agentic-search-discovery`

## Licence

MIT (see `LICENSE`).
