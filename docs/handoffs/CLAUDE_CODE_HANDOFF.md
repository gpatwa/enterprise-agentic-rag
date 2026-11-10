# Claude Code Handoff: agentic-resolution-intelligence

Updated: 2026-11-10 (the day this repository was extracted from the monorepo `gpatwa/enterprise-agentic-rag`).

## Where this came from

Extracted with `git filter-repo` (script: `scripts/separation/extract.sh` in the original repository; plan:
`docs/REPO_SEPARATION_EXTRACTION_PLAN.md` there). History and paths are preserved. Product history before the extraction
includes work on the sibling products' shared tooling.

## State

- The deployed pilots are unchanged by the split: Azure resources, state keys and URLs did not move.
- Open decisions that are the owner's: GitHub secrets for deploy workflows, any licence other than MIT, and the items listed
  in `CLAUDE.md` as human gates.
- Verified at extraction: the test command in `README.md` passes in a fresh clone of this repository.

## Next actions

1. Read `CLAUDE.md`, then verify real state (`git status -sb`, `gh pr list`) and report; the owner decides what comes next.
