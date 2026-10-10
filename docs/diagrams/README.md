# Architecture Diagrams

Archify JSON files are the source of truth for interactive architecture
diagrams in this directory. The generated HTML is committed so readers can use
the diagrams without installing project tooling.

| Source | Generated artifact | Purpose |
|---|---|---|
| `agentic-data-stack.architecture.json` | `agentic-data-stack-system.html` | High-level system boundaries and guided views |
| `agentic-data-stack-request.workflow.json` | `agentic-data-stack-request.html` | Request graph, trust gates, execution paths, and reviewed improvement loop |

Run these commands from the repository root:

```bash
make architecture-check
make architecture-build
```

`architecture-check` requires every source to pass Archify's `showcase`
profile. `architecture-build` also regenerates both standalone HTML files. Do
not edit generated HTML directly.

For a local browser containment and screenshot pass, run:

```bash
./scripts/architecture/archify.sh visual-check docs/diagrams/agentic-data-stack-system.html --json
./scripts/architecture/archify.sh visual-check docs/diagrams/agentic-data-stack-request.html --json
```

Visual-check sidecars are intentionally ignored; inspect them locally and keep
the versioned JSON and deterministic HTML as the reviewable artifacts.

The wrapper pins Archify to commit
`5769acefcc2ebd696a4f9ed3ac9cb6cca1d75c70`, verifies the checkout, installs
the upstream lockfile with lifecycle scripts disabled, and caches it under
`.cache/archify`. Updating that revision is an explicit dependency change and
requires rebuilding and visually reviewing both artifacts.

## Ownership

- Code, configuration, schemas, and migrations define runtime behavior.
- ADRs explain binding architectural decisions and tradeoffs.
- Archify sources explain the current system and request flow.
- Major boundary, trust, storage, or execution-path changes must update the
  affected Archify source, or state in the PR why there is no diagram impact.
- CI regenerates the HTML and fails when committed artifacts drift from JSON.
