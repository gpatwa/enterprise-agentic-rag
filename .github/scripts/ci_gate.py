"""One required check for every pull request into main.

Path-filtered workflows never start for PRs that do not touch their paths, so none of them can be a required
status check: a PR would wait for a check that will never report. This gate derives which workflows *should*
run from the workflow files themselves (their ``pull_request`` ``branches`` and ``paths``), then waits for those
runs on the PR's head commit and fails if one is missing, failed or cancelled. A PR that triggers no workflow
passes at once.

Only the GitHub Actions API is used (through the ``gh`` CLI); no PR code is executed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import yaml

GATE_FILE = "ci-gate.yml"
OK_CONCLUSIONS = {"success", "skipped", "neutral"}


class GateError(Exception):
    """Raised for patterns or workflow files the gate cannot interpret safely."""


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate the GitHub path-filter subset in use (``*``, ``**``, literals); refuse anything else."""
    if pattern.startswith("!") or any(ch in pattern for ch in "?+[]"):
        raise GateError(f"unsupported path pattern: {pattern!r}")
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _matches(patterns: list[str], value: str) -> bool:
    return any(glob_to_regex(p).match(value) for p in patterns)


@dataclass(frozen=True)
class Workflow:
    file: str
    name: str
    branches: tuple[str, ...]
    paths: tuple[str, ...]

    def expected_for(self, base_branch: str, changed: list[str]) -> bool:
        if self.branches and not _matches(list(self.branches), base_branch):
            return False
        if not self.paths:
            return True
        return any(_matches(list(self.paths), path) for path in changed)


def load_workflows(directory: Path) -> list[Workflow]:
    """Every workflow that triggers on ``pull_request``, except the gate itself."""
    found: list[Workflow] = []
    for path in sorted(directory.glob("*.y*ml")):
        if path.name == GATE_FILE:
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        on = data.get("on", data.get(True))  # PyYAML parses a bare `on:` key as boolean True
        if isinstance(on, str):
            on = {on: None}
        elif isinstance(on, list):
            on = {item: None for item in on}
        if not isinstance(on, dict) or "pull_request" not in on:
            continue
        trigger = on["pull_request"] or {}
        if trigger.get("paths-ignore"):
            raise GateError(f"{path.name}: paths-ignore is not supported by the gate")
        found.append(
            Workflow(
                file=path.name,
                name=str(data.get("name", path.name)),
                branches=tuple(trigger.get("branches") or ()),
                paths=tuple(trigger.get("paths") or ()),
            )
        )
    return found


def expected_workflows(workflows: list[Workflow], base_branch: str, changed: list[str]) -> list[Workflow]:
    return [w for w in workflows if w.expected_for(base_branch, changed)]


class Api(Protocol):
    def changed_files(self) -> list[str]: ...

    def latest_run(self, workflow_file: str) -> dict | None: ...


class GhApi:
    """Reads the PR's files and a workflow's runs for the head commit through ``gh api``."""

    def __init__(self, repo: str, pr_number: str, head_sha: str) -> None:
        self.repo, self.pr_number, self.head_sha = repo, pr_number, head_sha

    @staticmethod
    def _gh(*args: str) -> str:
        return subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True).stdout

    def changed_files(self) -> list[str]:
        out = self._gh(
            "--paginate",
            f"repos/{self.repo}/pulls/{self.pr_number}/files",
            "--jq",
            ".[] | .filename, (.previous_filename // empty)",
        )
        return sorted({line for line in out.splitlines() if line})

    def latest_run(self, workflow_file: str) -> dict | None:
        out = self._gh(
            f"repos/{self.repo}/actions/workflows/{workflow_file}/runs?head_sha={self.head_sha}&event=pull_request&per_page=20"
        )
        runs = json.loads(out).get("workflow_runs", [])
        return max(runs, key=lambda run: run["created_at"]) if runs else None


@dataclass(frozen=True)
class Outcome:
    ok: bool
    lines: tuple[str, ...]


def wait_for_runs(
    api: Api,
    expected: list[Workflow],
    *,
    appear_timeout: float = 180.0,
    overall_timeout: float = 2400.0,
    poll: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Outcome:
    """Wait until every expected workflow has a successful run, failing fast on any bad one."""
    if not expected:
        return Outcome(True, ("No workflow applies to the files in this pull request.",))
    start = clock()
    state: dict[str, str] = {}
    while True:
        pending = False
        for workflow in expected:
            run = api.latest_run(workflow.file)
            if run is None:
                if clock() - start > appear_timeout:
                    return Outcome(
                        False, (f"FAIL {workflow.name}: expected to run for this pull request but no run started.",)
                    )
                state[workflow.file] = f"waiting for {workflow.name} to start"
                pending = True
            elif run["status"] != "completed":
                state[workflow.file] = f"{workflow.name}: {run['status']}"
                pending = True
            elif run["conclusion"] in OK_CONCLUSIONS:
                state[workflow.file] = f"ok   {workflow.name}: {run['conclusion']}"
            else:
                return Outcome(False, (f"FAIL {workflow.name}: {run['conclusion']} ({run.get('html_url', 'no url')})",))
        if not pending:
            return Outcome(True, tuple(state[w.file] for w in expected))
        if clock() - start > overall_timeout:
            return Outcome(
                False,
                (
                    "FAIL timed out waiting for: "
                    + "; ".join(state[w.file] for w in expected if not state[w.file].startswith("ok")),
                ),
            )
        sleep(poll)


def main() -> int:
    repo, pr, sha, base = (os.environ[k] for k in ("REPO", "PR_NUMBER", "HEAD_SHA", "BASE_REF"))
    workflows = load_workflows(Path(".github/workflows"))
    api = GhApi(repo, pr, sha)
    changed = api.changed_files()
    expected = expected_workflows(workflows, base, changed)
    print(f"{len(changed)} changed files; expected workflows: {[w.file for w in expected] or 'none'}")
    outcome = wait_for_runs(api, expected)
    summary = "\n".join(["## CI gate", *(f"- {line}" for line in outcome.lines)])
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(summary + "\n", encoding="utf-8")
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    sys.exit(main())
