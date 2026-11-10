"""Make an extracted clone a standalone repository (X3/X4 of docs/REPO_SEPARATION_EXTRACTION_PLAN.md).

    python scripts/separation/adapt_clone.py <analytics|discovery|support> <clone-dir>

Edits the clone only and commits there. Nothing is pushed. It (1) drops the monorepo boundary check, which has nothing
left to compare, (2) rewrites the CI gate's repository-specific tests, (3) prunes Makefile targets that reference paths
the clone no longer has, and (4) writes the repository's README, CLAUDE.md and handoff. The wording of (4) claims only what
the code supports (plan section 3.2); the owner edits it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

NAMES = {
    "analytics": "agentic-data-analytics",
    "discovery": "agentic-search-discovery",
    "support": "agentic-resolution-intelligence",
}
SIBLINGS = "\n".join(f"- `{n}`" for n in NAMES.values())

GATE_TESTS = {
    "analytics": """def test_analytics_change_expects_the_analytics_workflow() -> None:
    assert "ci-analytics.yml" in _files([], "main", ["services/analytics-api/app/x.py"])
    assert "ci-landing.yml" not in _files([], "main", ["services/analytics-api/app/x.py"])


def test_contract_changes_run_the_analytics_backend() -> None:
    assert "ci-analytics.yml" in _files([], "main", ["packages/platform_contracts/evidence.py"])


def test_landing_change_expects_only_the_landing_workflow() -> None:
    assert _files([], "main", ["apps/landing/src/a.ts"]) == {"ci-landing.yml"}


def test_renamed_file_counts_by_old_path() -> None:
    assert "ci-landing.yml" in _files([], "main", ["apps/landing/old.ts", "elsewhere/new.ts"])


def test_branch_filter_excludes_stacked_prs() -> None:
    assert "ci-analytics.yml" not in _files([], "claude/other", ["services/analytics-api/app/x.py"])  # branches: [main]
""",
    "discovery": """def test_discovery_change_expects_only_discovery() -> None:
    assert _files([], "main", ["services/discovery-api/app/x.py"]) == {"ci-discovery.yml"}


def test_web_change_expects_discovery() -> None:
    assert _files([], "main", ["apps/discovery-web/src/a.ts"]) == {"ci-discovery.yml"}


def test_renamed_file_counts_by_old_path() -> None:
    assert "ci-discovery.yml" in _files([], "main", ["apps/discovery-web/old.ts", "elsewhere/new.ts"])


def test_branch_filter_excludes_stacked_prs() -> None:
    assert "ci-discovery.yml" not in _files([], "claude/other", ["services/discovery-api/app/x.py"])  # branches: [main]
""",
    "support": """def test_support_api_change_expects_the_support_workflow() -> None:
    assert "ci-support.yml" in _files([], "main", ["services/api/app/x.py"])
    assert "ci-support-web.yml" not in _files([], "main", ["services/api/app/x.py"])


def test_support_web_change_expects_the_web_workflow() -> None:
    assert "ci-support-web.yml" in _files([], "main", ["apps/support-web/src/a.ts"])


def test_renamed_file_counts_by_old_path() -> None:
    assert "ci-support-web.yml" in _files([], "main", ["apps/support-web/old.ts", "elsewhere/new.ts"])


def test_branch_filter_excludes_stacked_prs() -> None:
    assert "ci-support.yml" not in _files([], "claude/other", ["services/api/app/x.py"])  # branches: [main]
""",
}

DESCRIPTION = {
    "analytics": (
        "Governed natural-language analytics: an LLM interprets a question into a typed, validated intent, and a "
        "deterministic compiler, policy checks and human review do the rest. Callable by agents through typed tools and MCP. "
        "Includes the public landing site."
    ),
    "discovery": (
        "Hybrid (lexical and vector) search and personalised discovery over OpenSearch, with model use optional and off by "
        "default and an LLM-ready safety boundary. The agentic capability is the roadmap, not a current feature."
    ),
    "support": (
        "A LangGraph agent system that turns support tickets and knowledge into searchable resolution memory and "
        "evidence-backed answers, with reviewed agent commands."
    ),
}

AI_STATUS = {
    "analytics": (
        "**Agentic, governed.** A typed, durable graph runner (not LangGraph) with explicit node and edge allowlists, human "
        "review gates, and an agent tool surface plus an MCP adapter. The model does one bounded job: it turns a question into "
        'a typed `AnalyticalIntent` (validated, `extra="forbid"`) and drafts grounded explanations. Queries are compiled '
        "deterministically; the model never writes SQL.\n\n**Not claimed:** real-model accuracy (every evaluation used a "
        "scripted model and emulated PostgreSQL) and certified semantics (that gate is the owner's)."
    ),
    "discovery": (
        "**Not agentic yet.** There is no agent loop. Model use is optional and off by default (`no_model: True`); today the "
        "only model call is Azure OpenAI embeddings for vector and hybrid retrieval. The intent adapter has only a scripted "
        "provider, and the relevance judge and safety policy contain no model client.\n\n**Roadmap:** a real intent provider "
        "behind the existing `IntentProvider` interface, evaluated against the golden corpus, then an agent loop.\n\n**Not "
        "claimed:** LLM-powered or agentic search; learned personalisation or engagement gains (no consented behavioural data "
        "exists; the pilot runs a fictional catalogue)."
    ),
    "support": (
        "**Agentic.** A LangGraph graph (`services/api/app/agents/graph.py`) with clarify, context-enricher, planner, "
        "retriever, tool, evaluator and responder nodes, plus reviewed agent commands. Model clients for several backends "
        "live in `services/api/app/clients`.\n\n**Not claimed:** production use (it is not deployed) or answer quality (no "
        "live evaluation is recorded)."
    ),
}

TEST_CMD = {
    "analytics": "cd services/analytics-api && PYTHONPATH=.:../.. python3 -m pytest tests ../../packages -q",
    "discovery": "cd services/discovery-api && PYTHONPATH=. python3 -m pytest tests -q",
    "support": "cd services/api && PYTHONPATH=.:../.. python3 -m pytest tests/pipelines tests/test_tenant_data_isolation.py -q",
}

LAYOUT = {
    "analytics": "`services/analytics-api`, `apps/analytics-web`, `apps/landing`, `packages/platform_contracts`, "
    "`infra/terraform/azure-analytics-pilot`, `docs/execution/enterprise-analytics`",
    "discovery": "`services/discovery-api` (contracts in `app/contracts`), `apps/discovery-web`, "
    "`infra/terraform/azure-discovery-pilot`, `infra/terraform/github-repo`, `docs/execution/immersive-discovery`",
    "support": "`services/api`, `apps/support-web`, `pipelines`, `libs`, `models`, `eval`, `deploy`, the platform services "
    "(`control-plane`, `data-plane`, `gateway`, `sandbox`), `infra/terraform`",
}

EXTRA_RULES = {
    "analytics": (
        "- Semantic definitions are Git-backed. Never claim a contract is certified because code or a fixture refers to it; "
        "preserve the human semantic-certification gate.\n"
        "- Human gates (semantic certification, security, policy, thresholds, final go/no-go) need the owner's explicit "
        "approval. Record approvals in `docs/execution/enterprise-analytics/agentic-data-stack-program.yaml`; never infer one "
        "from implementation or tests.\n"
        "- The release manifest hashes files by path relative to this repository's root; keep the layout. Signatures bind "
        "`manifest_digest`, so sign off on the final manifest.\n"
    ),
    "discovery": (
        "- Local fake providers are the default. Live OpenSearch, Azure and cloud changes need the owner's explicit request "
        "in the task.\n"
        "- Say only what the code supports about AI: model use is optional and off by default.\n"
    ),
    "support": (
        "- Do not deploy or change cloud resources unless asked in the task. Local fakes are the default.\n"
        "- Say only what the code supports about AI; do not claim production use or answer quality without a recorded "
        "evaluation.\n"
    ),
}


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def drop_boundary_check(clone: Path) -> None:
    for rel in (".github/scripts/check_product_boundaries.py", ".github/scripts/test_check_product_boundaries.py"):
        (clone / rel).unlink(missing_ok=True)
    gate = clone / ".github/workflows/ci-gate.yml"
    text = gate.read_text()
    text = re.sub(
        r"      - name: Check that no product depends on another\n        run: python \.github/scripts/check_product_boundaries\.py\n",
        "",
        text,
    )
    gate.write_text(text)


def rewrite_gate_tests(clone: Path, product: str) -> None:
    path = clone / ".github/scripts/test_ci_gate.py"
    text = path.read_text()
    start = text.index("def test_discovery_change_expects_only_discovery")
    end = text.index("def test_the_gate_never_waits_for_itself")
    path.write_text(text[:start] + GATE_TESTS[product] + "\n\n" + text[end:])


PATH_LINE = re.compile(r'^(\s+- )"([^"]+)"\s*$')


def prune_workflow_paths(clone: Path) -> int:
    """Drop `paths:` entries whose literal prefix no longer exists in the clone (for example `packages/**`)."""
    removed = 0
    for wf in (clone / ".github/workflows").glob("*.yml"):
        out = []
        for line in wf.read_text().split("\n"):
            m = PATH_LINE.match(line)
            if m and ("/" in m.group(2) or m.group(2).endswith((".toml", ".yml", ".txt"))):
                prefix = re.split(r"[*?\[]", m.group(2))[0].rstrip("/")
                if prefix and not (clone / prefix).exists():
                    removed += 1
                    continue
            out.append(line)
        wf.write_text("\n".join(out))
    return removed


PATHISH = re.compile(
    r"(?<![\w.$])((?:services|apps|infra|scripts|docs|packages|pipelines|libs|models|eval|deploy)/[\w./-]+)"
)


def prune_makefile(clone: Path) -> tuple[int, int]:
    path = clone / "Makefile"
    lines = path.read_text().split("\n")
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        starts = re.match(r"^[A-Za-z0-9_.-]+:(?!=)", line) is not None
        if starts and current and not current[-1].startswith("#"):
            blocks.append(current)
            current = []
        elif starts and current and current[-1].startswith("#"):
            comments = []
            while current and current[-1].startswith("#"):
                comments.insert(0, current.pop())
            if current:
                blocks.append(current)
            current = comments
        current.append(line)
    if current:
        blocks.append(current)
    kept, dropped = [], 0
    for block in blocks:
        is_target = any(re.match(r"^[A-Za-z0-9_.-]+:(?!=)", line) for line in block)
        if is_target and not any(row.startswith(".PHONY") for row in block):
            missing = False
            for line in block:
                for match in PATHISH.findall(line):
                    token = match.rstrip("/.,;:)'\"")
                    if "*" in token or "$" in token:
                        continue
                    if not (clone / token).exists():
                        missing = True
            if missing:
                dropped += 1
                continue
        kept.append("\n".join(block))
    text = "\n".join(kept)
    # keep .PHONY honest
    targets = set(re.findall(r"^([A-Za-z0-9_.-]+):(?!=)", text, re.M))

    def phony(match: re.Match[str]) -> str:
        names = [n for n in match.group(1).replace("\\\n", " ").split() if n in targets]
        return ".PHONY: " + " ".join(names) if names else ""

    text = re.sub(r"^\.PHONY:((?:[^\n]*\\\n)*[^\n]*)", phony, text, flags=re.M)
    path.write_text(text)
    return len(re.findall(r"^[A-Za-z0-9_.-]+:(?!=)", text, re.M)), dropped


PRODUCT_SERVICES = {
    "analytics": ("analytics-api", "analytics-web"),
    "discovery": ("discovery-api", "discovery-web"),
}
OTHER_PRODUCT_SERVICES = {
    "analytics": ("discovery-api", "discovery-web", "support-api", "support-web"),
    "discovery": ("analytics-api", "analytics-web", "support-api", "support-web"),
    "support": ("analytics-api", "analytics-web", "discovery-api", "discovery-web"),
}
TEST_DIRS = {
    "analytics": "services/analytics-api/tests",
    "discovery": "services/discovery-api/tests",
    "support": "services/api/tests",
}


def _service_blocks(text: str) -> tuple[str, dict[str, str], str]:
    """Split docker-compose.yml into (preamble, {service: block}, rest) using the 2-space service keys."""
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line == "services:") + 1
    end = next((i for i in range(start, len(lines)) if lines[i] and not lines[i].startswith((" ", "#"))), len(lines))
    blocks: dict[str, list[str]] = {}
    order: list[str] = []
    current: list[str] | None = None
    carry: list[str] = []
    for line in lines[start:end]:
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            order.append(match.group(1))
            current = blocks.setdefault(match.group(1), [])
            current.extend(carry)
            carry = []
        if current is not None:
            current.append(line)
        else:
            carry.append(line)
    return "\n".join(lines[:start]), {k: "\n".join(v) for k, v in blocks.items()}, "\n".join(lines[end:])


def prune_compose(clone: Path, product: str) -> str:
    import yaml

    path = clone / "docker-compose.yml"
    if not path.exists():
        return "no compose file"
    text = path.read_text()
    head, blocks, rest = _service_blocks(text)
    parsed = yaml.safe_load(text)["services"]
    if product == "support":
        keep = {name for name in blocks if name not in OTHER_PRODUCT_SERVICES["support"]}
    else:
        keep = set(PRODUCT_SERVICES[product])
        todo = list(keep)
        while todo:
            deps = parsed[todo.pop()].get("depends_on") or {}
            for dep in deps if isinstance(deps, list) else deps.keys():
                if dep not in keep:
                    keep.add(dep)
                    todo.append(dep)
    out = head + "\n" + "\n".join(blocks[name] for name in blocks if name in keep) + "\n" + rest
    result = yaml.safe_load(out)["services"]
    for name, spec in result.items():
        deps = spec.get("depends_on") or {}
        for dep in deps if isinstance(deps, list) else deps.keys():
            assert dep in result, f"{name} depends on removed service {dep}"
        build = spec.get("build")
        if isinstance(build, dict):
            context = build.get("context", ".")
            assert (clone / context).exists(), f"{name}: build context {context} missing"
            dockerfile = build.get("dockerfile")
            if dockerfile:
                assert (clone / context / dockerfile).exists(), f"{name}: {context}/{dockerfile} missing"
    path.write_text(out)
    return f"compose services kept={len(result)}"


def prune_ignores(clone: Path) -> int:
    """Drop .gitignore/.dockerignore lines that name product directories this clone does not have."""
    removed = 0
    ref = re.compile(r"(?<![\w.])((?:services|apps|infra|packages|pipelines)/[\w./-]+)")
    for name in (".gitignore", ".dockerignore"):
        path = clone / name
        if not path.exists():
            continue
        out = []
        for line in path.read_text().split("\n"):
            match = ref.search(line)
            if match and not line.lstrip().startswith("#") and "*" not in match.group(1):
                top = "/".join(match.group(1).split("/")[:2])
                if top.startswith(("services/", "apps/")) and not (clone / top).exists():
                    removed += 1
                    continue
            out.append(line)
        path.write_text("\n".join(out))
    return removed


def prune_pyproject(clone: Path, product: str) -> None:
    path = clone / "pyproject.toml"
    text = path.read_text()

    def keep_existing(match: re.Match[str]) -> str:
        items = re.findall(r'"([^"]+)"', match.group(2))
        kept = [i for i in items if "/" not in i or (clone / i).exists()]
        return match.group(1) + "[" + ", ".join(f'"{i}"' for i in kept) + "]"

    text = re.sub(r"^(src = )\[([^\]]*)\]", keep_existing, text, flags=re.M)
    text = re.sub(
        r"^(known-first-party = )\[([^\]]*)\]",
        lambda m: (
            m.group(1)
            + "["
            + ", ".join(f'"{i}"' for i in re.findall(r'"([^"]+)"', m.group(2)) if i == "app" or (clone / i).exists())
            + "]"
        ),
        text,
        flags=re.M,
    )
    text = re.sub(r"^(testpaths = )\[[^\]]*\]", lambda m: m.group(1) + f'["{TEST_DIRS[product]}"]', text, flags=re.M)
    path.write_text(text)


def retarget_repo_settings(clone: Path, product: str) -> None:
    """Point the repo-settings tooling (copied into every repository) at this repository, not the monorepo."""
    name = NAMES[product]
    script = clone / "scripts/bootstrap_github_repo.sh"
    if script.exists():
        text = script.read_text()
        text = text.replace("${REPO:-gpatwa/enterprise-agentic-rag}", "${REPO:-gpatwa/" + name + "}")
        text = text.replace(
            "${STATE_KEY:-github-repo/terraform.tfstate}", "${STATE_KEY:-github-repo/" + name + ".tfstate}"
        )
        if product != "discovery":
            text = text.replace('${PROTECTED_ENVS:-[\\"discovery-pilot\\"]}', "${PROTECTED_ENVS:-[]}")
        script.write_text(text)
    stack = clone / "infra/terraform/github-repo/main.tf"
    if stack.exists():
        text = stack.read_text()
        text = text.replace('default = "enterprise-agentic-rag"', f'default = "{name}"')
        if product != "discovery":
            text = text.replace('default = ["discovery-pilot"]', "default = []")
        stack.write_text(text)


def write_docs(clone: Path, product: str) -> None:
    name = NAMES[product]
    others = "\n".join(f"- `{n}`" for k, n in NAMES.items() if k != product)
    readme = f"""# {name}

{DESCRIPTION[product]}

## What is agentic here

{AI_STATUS[product]}

## Layout

{LAYOUT[product]}.

## Test

```bash
{TEST_CMD[product]}
```

## Status

Pilot stage. Nothing here is production, and no compliance certification is claimed. Cloud changes (Terraform apply,
deploys) are made only on the owner's explicit request. See `CLAUDE.md` for the working rules and
`docs/handoffs/CLAUDE_CODE_HANDOFF.md` for the current state.

## Related repositories

This repository was extracted from a monorepo with its history. The products are independent and import nothing from each other:

{others}

## Licence

MIT (see `LICENSE`).
"""
    (clone / "README.md").write_text(readme)
    claude = f"""# Claude Code Repository Guide: {name}

## Start Here

Before changing files, inspect `git status -sb`, the current branch and recent commits. This repository may contain the
owner's work; never discard or overwrite unrelated changes. Read `docs/handoffs/CLAUDE_CODE_HANDOFF.md` for the current state.

## Boundaries

- This repository is one product: {DESCRIPTION[product]}
- Do not import code from the sibling products. They live in separate repositories:
{others}
{EXTRA_RULES[product]}
## Safety and workflow

- Do not deploy to Azure, mutate cloud resources, connect to a live warehouse or run live validation unless the owner
  explicitly asks in the current task. Local fake-provider verification is the default.
- Human gates (security, policy, thresholds, licensing, final go/no-go) need the owner's explicit approval. Never infer approval.
- Never set GitHub secrets or print credentials; never commit `backend.hcl`, `terraform.tfvars`, `secrets.auto.tfvars` or plan files.
- Merge your own pull requests once every check is green (`gh pr merge <n> --auto --merge`).
- Do not claim a test or evaluation passed unless you ran it.

## Useful commands

```bash
{TEST_CMD[product]}
ruff check <changed-python-files>
git diff --check
```
"""
    (clone / "CLAUDE.md").write_text(claude)
    handoff_dir = clone / "docs/handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    (handoff_dir / "CLAUDE_CODE_HANDOFF.md").write_text(f"""# Claude Code Handoff: {name}

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
""")


def main() -> int:
    product, clone = sys.argv[1], Path(sys.argv[2])
    drop_boundary_check(clone)
    rewrite_gate_tests(clone, product)
    kept, dropped = prune_makefile(clone)
    removed = prune_workflow_paths(clone)
    compose = prune_compose(clone, product)
    ignores = prune_ignores(clone)
    prune_pyproject(clone, product)
    retarget_repo_settings(clone, product)
    write_docs(clone, product)
    run("git", "add", "-A", cwd=clone)
    run(
        "git",
        "commit",
        "-q",
        "-m",
        f"Standalone repository: {NAMES[product]} (CI gate tests, Makefile, README, CLAUDE.md, handoff)\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>",
        cwd=clone,
    )
    print(
        f"{product}: Makefile targets kept={kept} dropped={dropped}; workflow path filters removed={removed}; {compose}; ignore lines removed={ignores}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
