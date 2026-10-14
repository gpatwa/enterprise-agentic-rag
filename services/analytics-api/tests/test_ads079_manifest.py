"""ADS-079: the evidence manifest links artifacts by digest, lists blockers, never decides, never signs, and detects tampering."""

from __future__ import annotations

import copy
import json

import pytest
from reference_stack import release_manifest as rm

MANIFEST = rm.build_manifest()


def test_the_manifest_is_consistent_and_verifies():
    assert rm.verify_manifest(MANIFEST) == []
    assert MANIFEST["manifest_version"] == rm.MANIFEST_VERSION and len(MANIFEST["manifest_digest"]) == 64


def test_it_links_code_contracts_prompts_policies_corpus_reports_runbooks_and_containers():
    groups = MANIFEST["artifacts"]
    assert {
        "code",
        "contracts",
        "semantic_registry",
        "prompts",
        "policies_and_thresholds",
        "corpora",
        "reports",
        "runbooks",
        "containers",
    } <= set(groups)
    assert all(groups[g] for g in groups)
    assert any(k.endswith("ops-restore.md") for k in groups["runbooks"]) and any(
        "m7/corpus-v1.json" in k for k in groups["corpora"]
    )
    assert MANIFEST["models"]["selected"] is None and "no images were built" in MANIFEST["containers_note"]


def test_the_generator_never_decides_and_never_signs():
    assert MANIFEST["decision"] == "pending_human_review"
    assert MANIFEST["signatures"] == {role: None for role in rm.SIGN_OFF_ROLES}
    assert set(rm.SIGN_OFF_ROLES) == {"product", "engineering", "data_owner", "security", "operations"}
    assert not rm.sign_off_complete(MANIFEST)


def test_the_blockers_are_listed_and_include_the_real_open_items():
    text = "\n".join(MANIFEST["blocking_reasons"])
    assert "not approved by a person" in text and "reference corpus is not approved" in text
    assert "human gate not approved: M7" in text and "no independent review" in text
    assert "F-03" in text and "no signed human sign-off" in text
    assert "ADS-076" in text and "answers_per_tenant_day" in text  # an unmet gate is surfaced, not smoothed over


def test_every_evaluation_is_present_and_summarised():
    names = {e["name"] for e in MANIFEST["evaluations"]}
    assert {f"ADS-0{n}" for n in (69, 71, 72, 73, 74, 75, 76, 77, 78)} <= names
    assert all(e["present"] for e in MANIFEST["evaluations"])
    assert all(
        e["approval"] != "approved" or e["name"].startswith(("ADS-049", "ADS-051", "ADS-052", "ADS-053"))
        for e in MANIFEST["evaluations"]
    )


def test_a_changed_artifact_a_forged_decision_and_a_forged_signature_are_detected():
    tampered = copy.deepcopy(MANIFEST)
    first = next(iter(tampered["artifacts"]["code"]))
    tampered["artifacts"]["code"][first] = "0" * 64
    assert any("changed since" in p or "digest does not match" in p for p in rm.verify_manifest(tampered))
    decided = copy.deepcopy(MANIFEST)
    decided["decision"] = "go"
    assert any("pending_human_review" in p for p in rm.verify_manifest(decided))
    forged = copy.deepcopy(MANIFEST)
    forged["signatures"]["security"] = {"signer": "", "statement": "ok", "manifest_digest": MANIFEST["manifest_digest"]}
    assert any("security" in p for p in rm.verify_manifest(forged))
    wrong_digest = copy.deepcopy(MANIFEST)
    wrong_digest["signatures"]["security"] = {
        "signer": "A. Person",
        "statement": "approved",
        "manifest_digest": "f" * 64,
    }
    assert any("security" in p for p in rm.verify_manifest(wrong_digest))


def test_a_named_persons_signature_over_the_digest_is_accepted_but_one_signature_is_not_a_go():
    signed = copy.deepcopy(MANIFEST)
    signed["signatures"]["security"] = {
        "signer": "A. Person",
        "statement": "I reviewed it",
        "manifest_digest": MANIFEST["manifest_digest"],
    }
    assert rm.verify_manifest(signed) == [] and not rm.sign_off_complete(signed)
    for role in rm.SIGN_OFF_ROLES:
        signed["signatures"][role] = {
            "signer": "A. Person",
            "statement": "I reviewed it",
            "manifest_digest": MANIFEST["manifest_digest"],
        }
    assert (
        rm.sign_off_complete(signed) and signed["decision"] == "pending_human_review"
    )  # even complete sign-off leaves the decision to people


def test_a_missing_report_blocks(tmp_path):
    manifest = rm.build_manifest(reports_dir=tmp_path)
    assert any("evaluation report missing" in r for r in manifest["blocking_reasons"])


def test_a_failing_report_is_listed_as_a_blocker(tmp_path):
    for path in rm.REPORTS.glob("*.json"):
        (tmp_path / path.name).write_text(path.read_text())
    broken = tmp_path / "ADS-074-isolation-report.json"
    data = json.loads(broken.read_text())
    data["ok"] = False
    broken.write_text(json.dumps(data))
    assert any("evaluation not met: ADS-074" in r for r in rm.build_manifest(reports_dir=tmp_path)["blocking_reasons"])


def test_the_checked_in_manifest_still_matches_the_files_it_links():
    stored = json.loads((rm.REPORTS / "ADS-079-evidence-manifest.json").read_text())
    if stored["base_commit"] != MANIFEST["base_commit"]:
        pytest.skip(
            "the checked-in manifest was generated at another commit; regenerate with make analytics-m7-manifest"
        )
    assert rm.verify_manifest(stored) == []
