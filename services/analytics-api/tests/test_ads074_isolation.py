"""ADS-074: the hostile-probe matrix passes, and each class of probe is shown able to fail when its defence is removed."""

from __future__ import annotations

import json

import pytest
from reference_stack import isolation_eval as ev

from app.runtime.analyze_service import GovernedAnalyzeService
from packages.platform_contracts.security import AnalyticsIdentity

THRESHOLDS = json.loads(ev.THRESHOLDS.read_text())


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return ev.run_isolation(root=tmp_path_factory.mktemp("isolation"))


def test_every_probe_is_refused_without_leaking_and_the_gates_are_met(report):
    assert report["ok"], [(n, g["value"]) for n, g in report["gates"].items() if not g["meets"]]
    assert not [p["name"] for p in report["probes"] if not p["passed"]]
    assert {p["group"] for p in report["probes"]} == {"cross_tenant", "purpose", "duties", "auth"}
    assert {p["surface"] for p in report["probes"]} == {"rest", "tools"}
    assert report["samples"]["probes"] >= 24 and THRESHOLDS["approval"]["status"] == "proposed"


def test_thresholds_are_proposed_and_the_report_is_not_a_security_review(report):
    text = ev.render_markdown(report)
    assert "NOT APPROVED" in text and "not an independent security review" in text
    assert "automated_actor_naming" in text and "F-03" in text  # open findings and the naming caveat are visible


def test_open_security_findings_are_carried_into_the_report_not_hidden(report):
    assert any(f.startswith("F-03") for f in report["open_findings"])


def test_broken_tenant_scoping_is_caught_as_a_cross_tenant_leak(monkeypatch, tmp_path):
    original = GovernedAnalyzeService.status

    def careless(self, identity, *, purpose, run_id):
        return original(self, identity.model_copy(update={"tenant_id": "tenant-a"}), purpose=purpose, run_id=run_id)

    monkeypatch.setattr(GovernedAnalyzeService, "status", careless)
    report = ev.run_isolation(root=tmp_path)
    assert report["gates"]["cross_tenant_leaks"]["value"] > 0 and not report["ok"]


def test_a_verifier_that_accepts_any_token_is_caught_as_unauthenticated_access(monkeypatch, tmp_path):
    from app.security import OIDCVerifier

    monkeypatch.setattr(
        OIDCVerifier,
        "verify",
        lambda self, token: AnalyticsIdentity(
            tenant_id="tenant-a", user_id="requester", purposes=[ev.PURPOSE], groups=["analyst"]
        ),
    )
    report = ev.run_isolation(root=tmp_path)
    assert report["gates"]["unauthenticated_successes"]["value"] > 0 and not report["ok"]


def test_dropping_the_purpose_check_is_caught(monkeypatch, tmp_path):
    original = GovernedAnalyzeService.status

    def careless(self, identity, *, purpose, run_id):
        return original(self, identity.model_copy(update={"purposes": [purpose]}), purpose=purpose, run_id=run_id)

    monkeypatch.setattr(GovernedAnalyzeService, "status", careless)
    report = ev.run_isolation(root=tmp_path)
    assert report["gates"]["purpose_violations"]["value"] > 0 and not report["ok"]


def test_letting_automated_callers_review_is_caught(monkeypatch, tmp_path):
    import app.review.rules as rules

    monkeypatch.setattr(rules, "is_automated", lambda user_id: False)
    report = ev.run_isolation(root=tmp_path)
    assert report["gates"]["separation_of_duties_violations"]["value"] > 0 and not report["ok"]
    assert [p["name"] for p in report["probes"] if not p["passed"]] == ["an automated caller approves a review"]
