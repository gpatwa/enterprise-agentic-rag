"""ADS-070: the 100-case reference corpus is sound, independent of the system under test, pinned, and not approved by anyone."""

from __future__ import annotations

import copy
import json
from collections import Counter

from reference_stack import m7_corpus as corpus_module

RAW = corpus_module.CORPUS.read_bytes()
CORPUS = json.loads(RAW)
APPROVAL = json.loads(corpus_module.APPROVAL.read_text())


def test_the_corpus_has_100_cases_a_realistic_mix_and_no_structural_problems():
    cases = CORPUS["cases"]
    assert len(cases) == 100 and corpus_module.corpus_problems(CORPUS) == []
    kinds = Counter(c["kind"] for c in cases)
    assert kinds["answer"] >= 50 and all(
        kinds[k] >= 4 for k in ("refuse_no_execution", "policy_denied", "tenant_isolation", "clarify", "review")
    )
    assert 25 <= sum(1 for c in cases if c.get("p0")) <= 50


def test_the_corpus_digest_is_pinned_and_the_checked_in_file_is_what_the_builder_makes():
    assert corpus_module.digest(RAW) == APPROVAL["corpus_sha256"]
    assert corpus_module.render(corpus_module.build()) == RAW  # regenerate, never hand-edit


def test_expected_rows_are_independent_of_the_pipeline_and_match_known_values():
    assert corpus_module.expected("total") == (1, [["5050"]])
    assert corpus_module.expected("by_status")[1] == [["paid", "4000"], ["refunded", "1050"]]
    assert corpus_module.expected("monthly_paid")[1] == [
        ["2024-03-01", "1969"],
        ["2024-02-01", "1468"],
        ["2024-01-01", "563"],
    ]
    assert corpus_module.expected("monthly_all")[1] == [
        ["2024-03-01", "2494"],
        ["2024-02-01", "1853"],
        ["2024-01-01", "703"],
    ]
    assert corpus_module.expected("top_status")[1] == [["paid", "4000"]]
    imports = (corpus_module.HERE.parent / "m7_corpus.py").read_text()
    assert "from app" not in imports and "import app" not in imports  # the oracle does not touch the system under test


def test_a_wrong_expectation_a_missing_kind_or_a_duplicate_is_detected():
    wrong = copy.deepcopy(CORPUS)
    wrong["cases"][0]["expect_rows"] = [["1"]]
    assert any("expectation differs" in p for p in corpus_module.corpus_problems(wrong))
    short = copy.deepcopy(CORPUS)
    short["cases"] = [c for c in short["cases"] if c["kind"] != "review"]
    assert any("100 cases" in p for p in corpus_module.corpus_problems(short))
    assert any("no review" in p for p in corpus_module.corpus_problems(short))
    dup = copy.deepcopy(CORPUS)
    dup["cases"][1]["question"] = dup["cases"][0]["question"]
    assert any("duplicate" in p for p in corpus_module.corpus_problems(dup))
    few_p0 = copy.deepcopy(CORPUS)
    for case in few_p0["cases"]:
        case["p0"] = False
    assert any("P0" in p for p in corpus_module.corpus_problems(few_p0))


def test_a_changed_corpus_no_longer_matches_the_pinned_digest():
    edited = copy.deepcopy(CORPUS)
    edited["cases"][0]["question"] += "!"
    assert corpus_module.digest(corpus_module.render(edited)) != APPROVAL["corpus_sha256"]


def test_nobody_has_approved_the_corpus_and_the_limits_are_stated():
    approval = APPROVAL["approval"]
    assert (
        approval["status"] == "proposed" and approval["definitions_owner"] is None and approval["results_owner"] is None
    )
    assert any("scripted model" in limit for limit in APPROVAL["limits"])
    assert any("real ones" in limit for limit in APPROVAL["limits"])
