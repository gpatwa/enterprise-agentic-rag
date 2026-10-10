# LLM Resolution Task Packets

The canonical task list, dependencies, cost controls, dispatch waves, and
review gates are maintained in the
[LLM Search and Resolution Intelligence Execution Plan](../../LLM_RESOLUTION_INTELLIGENCE_EXECUTION_PLAN.md).

Use one task ID per Luna session. Give the model the canonical plan and one
packet only. Do not include chat history or unrelated architecture documents.

Current checkpoint: **LLM-057 complete**. The resolution workflow is approved
for local demo use only. Production approval remains blocked on live provider,
real-model, operational, performance, security sign-off, and deployment
evidence; Azure deployment is deferred.

## First Dispatch Wave

| Task | Purpose | Can run concurrently |
|---|---|---|
| [LLM-001](LLM-001-architecture-adr.md) | LLM role and trust-boundary ADR | Yes, with LLM-002 |
| [LLM-002](LLM-002-golden-corpus.md) | Adversarial resolution golden corpus | Yes, with LLM-001 |

Both tasks are documentation/fixture work and require no live model, external
service, or cloud deployment. Merge and review both before dispatching typed
contract work.

## Packet Rules

- Name packets `LLM-NNN-short-description.md`.
- Copy dependencies, owned files, acceptance evidence, exact reads, targeted
  tests, stop conditions, and commit subject from the canonical plan.
- Keep each session within the Luna execution limits in Section 6 of the plan.
- Add a dedicated packet only when examples or constraints do not fit cleanly
  in the canonical task row.

## Integration Gate

The integration owner, not every Luna task, runs:

```bash
PYTHONPATH="$PWD/services/api:$PWD" pytest services/api/tests -q
npm --prefix apps/support-web run typecheck
npm --prefix apps/support-web test -- --run
git diff --check
```
