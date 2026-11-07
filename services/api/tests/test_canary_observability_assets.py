"""The canary dashboard and alert rules must only reference metrics and label values the code really emits.

Rule behaviour itself is proven separately with promtool:
    docker run --rm -v "$PWD/infra/observability/alerts:/w" --entrypoint promtool prom/prometheus:v3.1.0 \
        test rules /w/rag-opensearch-canary.tests.yml
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from prometheus_client import REGISTRY

import app.search.retrieval_metrics  # noqa: F401  (registers the metrics)

OBS = Path(__file__).resolve().parents[3] / "infra" / "observability"
RULES = OBS / "alerts" / "rag-opensearch-canary.rules.yml"
DASHBOARD = OBS / "grafana" / "dashboards" / "rag-opensearch-canary.json"

ALLOWED_LABELS = {
    "backend": {"opensearch", "qdrant"},
    "role": {"served", "shadow", "fallback"},
    "outcome": {"ok", "error", "timeout"},
    "result": {"compared", "opensearch_error"},
}


def _exposed_sample_names() -> set[str]:
    names: set[str] = set()
    for family in REGISTRY.collect():
        if not family.name.startswith("rag_"):
            continue
        if family.type == "counter":
            names.add(family.name + "_total")
        elif family.type == "histogram":
            names.update(family.name + suffix for suffix in ("_bucket", "_sum", "_count"))
    return names


def _rule_expressions() -> list[str]:
    groups = yaml.safe_load(RULES.read_text())["groups"]
    return [rule["expr"] for group in groups for rule in group["rules"]]


def _dashboard_expressions() -> list[str]:
    dashboard = json.loads(DASHBOARD.read_text())
    return [target["expr"] for panel in dashboard["panels"] for target in panel.get("targets", [])]


def test_every_rag_metric_in_rules_and_dashboard_is_exposed_by_the_code() -> None:
    exposed = _exposed_sample_names()
    assert exposed, "no rag_ metrics registered"
    for expression in _rule_expressions() + _dashboard_expressions():
        for name in re.findall(r"\brag_[a-z_]+\b", expression):
            assert name in exposed, f"{name} is not emitted by app.search.retrieval_metrics"


def test_label_values_in_queries_exist() -> None:
    for expression in _rule_expressions() + _dashboard_expressions():
        for label, matcher, value in re.findall(r'\b(backend|role|outcome|result)(=~?)"([^"]+)"', expression):
            for part in value.split("|") if matcher == "=~" else [value]:
                assert part in ALLOWED_LABELS[label], f'{label}="{part}" is never emitted'


def test_dashboard_is_well_formed() -> None:
    dashboard = json.loads(DASHBOARD.read_text())
    assert dashboard["uid"] == "rag-opensearch-canary" and dashboard["panels"]
    for panel in dashboard["panels"]:
        assert panel["title"] and panel["gridPos"]["w"] <= 24
        if panel["type"] != "text":
            assert panel["targets"] and all(t["expr"].strip() for t in panel["targets"])


def test_every_alert_has_a_severity_and_the_promtool_tests_cover_each_threshold_alert() -> None:
    groups = yaml.safe_load(RULES.read_text())["groups"]
    alerts = {rule["alert"]: rule for group in groups for rule in group["rules"]}
    assert all(rule["labels"]["severity"] in {"critical", "warning", "info"} for rule in alerts.values())
    tested = set(re.findall(r"alertname: (\w+)", (OBS / "alerts" / "rag-opensearch-canary.tests.yml").read_text()))
    untested = set(alerts) - tested
    assert not untested, f"no promtool test for {sorted(untested)}"
