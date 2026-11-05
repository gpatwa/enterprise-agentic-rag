"""Tests for the CI gate: path matching, expected-workflow selection against the real workflow files, and waiting."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import ci_gate as gate  # noqa: E402

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"


def _files(names: list[str], base: str, changed: list[str]) -> set[str]:
    return {w.file for w in gate.expected_workflows(gate.load_workflows(WORKFLOWS), base, changed)}


# ---- glob translation ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("apps/landing/**", "apps/landing/src/a/b.ts", True),
        ("apps/landing/**", "apps/landing-x/a.ts", False),
        ("apps/landing/**", "apps/landing", False),
        ("pyproject.toml", "pyproject.toml", True),
        ("pyproject.toml", "sub/pyproject.toml", False),
        ("services/analytics-api/tests/test_ads02*.py", "services/analytics-api/tests/test_ads021_x.py", True),
        ("services/analytics-api/tests/test_ads02*.py", "services/analytics-api/tests/sub/test_ads021.py", False),
        ("**/x.md", "x.md", True),
        ("**/x.md", "a/b/x.md", True),
        ("docs/execution/enterprise-analytics/ADS-02*.md", "docs/execution/enterprise-analytics/ADS-021-a.md", True),
    ],
)
def test_glob_semantics(pattern: str, path: str, expected: bool) -> None:
    assert bool(gate.glob_to_regex(pattern).match(path)) is expected


@pytest.mark.parametrize("pattern", ["!docs/**", "a?b", "a[bc]", "a+"])
def test_unsupported_patterns_fail_loudly(pattern: str) -> None:
    with pytest.raises(gate.GateError):
        gate.glob_to_regex(pattern)


# ---- selection against the real workflow files -------------------------------------------------------------------


def test_docs_only_pr_expects_nothing() -> None:
    assert _files([], "main", ["docs/RAG_PIPELINE_OPENSEARCH_INDEXER_PLAN.md"]) == set()


def test_discovery_change_expects_only_discovery() -> None:
    assert _files([], "main", ["services/discovery-api/app/x.py"]) == {"ci-discovery.yml"}


def test_shared_contracts_run_every_backend_that_uses_them() -> None:
    got = _files([], "main", ["packages/platform_contracts/evidence.py"])
    assert {"ci-analytics.yml", "ci-support.yml", "ci-discovery.yml", "ci-agentic-eval.yml"} <= got
    assert "ci-landing.yml" not in got


def test_renamed_file_counts_by_old_path() -> None:
    assert "ci-landing.yml" in _files([], "main", ["apps/landing/old.ts", "elsewhere/new.ts"])


def test_branch_filter_excludes_stacked_prs_but_not_unfiltered_workflows() -> None:
    got = _files([], "claude/other", ["services/discovery-api/app/x.py", "packages/platform_contracts/a.py"])
    assert "ci-discovery.yml" not in got  # branches: [main]
    assert "ci-agentic-eval.yml" in got  # no branch filter


def test_the_gate_never_waits_for_itself_or_for_manual_workflows() -> None:
    names = {w.file for w in gate.load_workflows(WORKFLOWS)}
    assert gate.GATE_FILE not in names and not any(n.startswith("deploy") for n in names)


def test_workflow_without_filters_is_always_expected(tmp_path: Path) -> None:
    (tmp_path / "a.yml").write_text("name: A\non:\n  pull_request:\n", encoding="utf-8")
    (tmp_path / "b.yml").write_text("name: B\non: [push, pull_request]\n", encoding="utf-8")
    (tmp_path / "c.yml").write_text("name: C\non:\n  push:\n", encoding="utf-8")
    assert {w.file for w in gate.expected_workflows(gate.load_workflows(tmp_path), "main", ["x"])} == {"a.yml", "b.yml"}


def test_paths_ignore_is_refused(tmp_path: Path) -> None:
    (tmp_path / "a.yml").write_text("name: A\non:\n  pull_request:\n    paths-ignore: ['docs/**']\n", encoding="utf-8")
    with pytest.raises(gate.GateError, match="paths-ignore"):
        gate.load_workflows(tmp_path)


# ---- waiting ---------------------------------------------------------------------------------------------------


class FakeApi:
    def __init__(self, runs: dict[str, list[dict | None]]) -> None:
        self.runs = runs
        self.calls: dict[str, int] = {}

    def changed_files(self) -> list[str]:
        return []

    def latest_run(self, workflow_file: str) -> dict | None:
        sequence = self.runs[workflow_file]
        index = min(self.calls.get(workflow_file, 0), len(sequence) - 1)
        self.calls[workflow_file] = self.calls.get(workflow_file, 0) + 1
        return sequence[index]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _wf(name: str) -> gate.Workflow:
    return gate.Workflow(file=f"{name}.yml", name=name, branches=(), paths=())


def _run(status: str, conclusion: str | None = None) -> dict:
    return {"status": status, "conclusion": conclusion, "created_at": "2026-11-05T00:00:00Z", "html_url": "u"}


def _wait(api: FakeApi, expected: list[gate.Workflow], **kw: float) -> gate.Outcome:
    clock = Clock()
    return gate.wait_for_runs(api, expected, sleep=clock.sleep, clock=clock, **kw)


def test_nothing_expected_passes_immediately() -> None:
    assert _wait(FakeApi({}), []).ok


def test_waits_through_in_progress_then_passes() -> None:
    api = FakeApi({"a.yml": [None, _run("queued"), _run("in_progress"), _run("completed", "success")]})
    assert _wait(api, [_wf("a")]).ok and api.calls["a.yml"] == 4


def test_skipped_and_neutral_count_as_ok() -> None:
    api = FakeApi({"a.yml": [_run("completed", "skipped")], "b.yml": [_run("completed", "neutral")]})
    assert _wait(api, [_wf("a"), _wf("b")]).ok


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
def test_any_bad_conclusion_fails_fast(conclusion: str) -> None:
    api = FakeApi({"a.yml": [_run("completed", conclusion)], "b.yml": [_run("in_progress")]})
    outcome = _wait(api, [_wf("a"), _wf("b")])
    assert not outcome.ok and "a" in outcome.lines[0]
    assert api.calls.get("b.yml", 0) == 0  # failed before waiting on the second


def test_an_expected_run_that_never_starts_fails() -> None:
    outcome = _wait(FakeApi({"a.yml": [None]}), [_wf("a")], appear_timeout=60.0)
    assert not outcome.ok and "no run started" in outcome.lines[0]


def test_overall_timeout_fails_with_what_was_pending() -> None:
    outcome = _wait(FakeApi({"a.yml": [_run("in_progress")]}), [_wf("a")], overall_timeout=100.0)
    assert not outcome.ok and "timed out" in outcome.lines[0]


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_a_persistently_failing_gh_call_reports_the_error_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *a, **k: calls.append(1) or _Result(1, stderr="HTTP 403: Resource not accessible"),
    )
    api = gate.GhApi("o/r", "1", "sha")
    with pytest.raises(gate.GateError, match="Resource not accessible"):
        api._gh("x", sleep=lambda s: None)
    assert len(calls) == api.attempts


def test_a_transient_gh_failure_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        [_Result(1, stderr="HTTP 502"), _Result(1, stderr="HTTP 422 diff not ready"), _Result(0, stdout="ok")]
    )
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: next(results))
    waits: list[float] = []
    assert gate.GhApi("o/r", "1", "sha")._gh("x", sleep=waits.append) == "ok"
    assert waits == [5.0, 10.0]
