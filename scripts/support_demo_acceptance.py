#!/usr/bin/env python3
"""Local acceptance check for Resolution Intelligence demo workflow."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8080"


class AcceptanceError(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AcceptanceError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AcceptanceError(f"{method} {path} failed: {exc.reason}") from exc

        return json.loads(body) if body else {}

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("POST", path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL. Default: {DEFAULT_BASE_URL}",
    )
    parser.add_argument("--timeout", type=float, default=180.0, help="HTTP request timeout in seconds.")
    args = parser.parse_args()

    client = Client(args.base_url, args.timeout)
    started = time.monotonic()
    checks: list[tuple[str, Any]] = []

    health = client.get("/health/liveness")
    expect(health.get("status") == "ok", "API liveness check failed")
    checks.append(("health", health["status"]))

    token = client.post(
        "/auth/token",
        {"user_id": "support-demo-acceptance", "role": "admin", "tenant_id": "default"},
    )
    client.token = token["access_token"]
    checks.append(("auth", token["tenant_id"]))

    jobs = client.get("/api/v1/support/jobs?limit=20")
    expect("jobs" in jobs, "support jobs response missing jobs array")
    checks.append(("jobs", len(jobs["jobs"])))

    seed = client.post("/api/v1/support/demo/seed")
    expect(seed.get("index_status") == "succeeded", f"demo seed/index failed: {seed.get('index_error')}")
    checks.append(("seed_index", seed["index_status"]))

    indexed = client.post("/api/v1/support/index?limit=100")
    index_summary = indexed.get("index") or {}
    total_sources = sum(
        int(index_summary.get(key) or 0)
        for key in ("tickets_total", "comments_total", "articles_total")
    )
    expect(not index_summary.get("errors"), f"support index returned errors: {index_summary['errors']}")
    expect(total_sources > 0, "support index did not see any demo support records")
    checks.append(("index", f"{total_sources} sources, {index_summary.get('skipped', 0)} skipped"))

    query = urllib.parse.urlencode({"q": "export timeout csv report", "limit": 5})
    search = client.get(f"/api/v1/support/search?{query}")
    search_results = search.get("results") or []
    expect(len(search_results) >= 3, "expected at least 3 similar support results")
    expect(
        any(result.get("retrieval_source") == "hybrid" for result in search_results),
        "expected at least one hybrid retrieval result",
    )
    checks.append(("hybrid_search", f"{len(search_results)} results"))

    resolution = client.post(
        "/api/v1/support/resolve",
        {"question": "How have we resolved export timeout issues?", "limit": 5},
    ).get("resolution") or {}
    citations = resolution.get("citations") or []
    expect(citations, "resolution response missing citations")
    expect("[1]" in (resolution.get("answer") or ""), "resolution answer is missing citation label [1]")
    expect(citations[0].get("source_id"), "first citation missing source_id")
    checks.append(("cited_resolution", f"{len(citations)} citations"))

    repeats = client.get("/api/v1/support/insights/repeats?limit=200&min_count=2")
    insights = repeats.get("insights") or []
    summary = repeats.get("summary") or {}
    expect(summary.get("repeat_clusters", 0) >= 2, "expected at least 2 repeat clusters")
    export_cluster = next((item for item in insights if item.get("title") == "Export + Timeout"), None)
    expect(export_cluster is not None, "missing Export + Timeout repeat cluster")
    checks.append(("repeat_clusters", summary["repeat_clusters"]))

    workflow = client.post(
        "/api/v1/support/insights/repeats/workflow",
        {"cluster_id": export_cluster["id"]},
    ).get("workflow") or {}
    playbook = workflow.get("playbook") or {}
    knowledge_gap = workflow.get("knowledge_gap") or {}
    deflection = workflow.get("deflection_estimate") or {}
    expect(playbook.get("status") == "ready_for_agent_review", "playbook is not ready for review")
    expect(playbook.get("citations"), "workflow playbook missing citations")
    expect(knowledge_gap.get("status") == "missing_kb_or_macro", "unexpected KB gap status")
    expect(deflection.get("potential_ticket_count", 0) >= 1, "deflection estimate missing repeat ticket count")
    checks.append(("workflow", f"{workflow.get('cluster', {}).get('title')} -> {playbook['status']}"))

    elapsed = time.monotonic() - started
    print("Resolution Intelligence local acceptance: PASS")
    for name, value in checks:
        print(f"  - {name}: {value}")
    print(f"  - elapsed_seconds: {elapsed:.2f}")
    return 0


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as exc:
        print(f"Resolution Intelligence local acceptance: FAIL\n  - {exc}", file=sys.stderr)
        raise SystemExit(1)
