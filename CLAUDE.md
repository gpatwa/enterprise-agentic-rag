# Claude Code Repository Guide: agentic-resolution-intelligence

## Start Here

Before changing files, inspect `git status -sb`, the current branch and recent commits. This repository may contain the
owner's work; never discard or overwrite unrelated changes. Read `docs/handoffs/CLAUDE_CODE_HANDOFF.md` for the current state.

## Boundaries

- This repository is one product: A LangGraph agent system that turns support tickets and knowledge into searchable resolution memory and evidence-backed answers, with reviewed agent commands.
- Do not import code from the sibling products. They live in separate repositories:
- `agentic-data-analytics`
- `agentic-search-discovery`
- Do not deploy or change cloud resources unless asked in the task. Local fakes are the default.
- Say only what the code supports about AI; do not claim production use or answer quality without a recorded evaluation.

## Safety and workflow

- Do not deploy to Azure, mutate cloud resources, connect to a live warehouse or run live validation unless the owner
  explicitly asks in the current task. Local fake-provider verification is the default.
- Human gates (security, policy, thresholds, licensing, final go/no-go) need the owner's explicit approval. Never infer approval.
- Never set GitHub secrets or print credentials; never commit `backend.hcl`, `terraform.tfvars`, `secrets.auto.tfvars` or plan files.
- Merge your own pull requests once every check is green (`gh pr merge <n> --auto --merge`).
- Do not claim a test or evaluation passed unless you ran it.

## Useful commands

```bash
cd services/api && PYTHONPATH=.:../.. python3 -m pytest tests/pipelines tests/test_tenant_data_isolation.py -q
ruff check <changed-python-files>
git diff --check
```
