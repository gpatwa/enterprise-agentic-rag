"""ADS-072: retrieval recall, filters, provenance, freshness, and token efficiency, and proof that each gate can fail."""

from __future__ import annotations

import copy
import json

import pytest
from reference_stack import retrieval_eval as ev

THRESHOLDS = json.loads(ev.THRESHOLDS.read_text())
CORPUS = json.loads(ev.CORPUS.read_bytes())


def test_the_corpus_is_pinned_and_the_checked_in_file_is_what_the_builder_makes():
    assert ev.corpus_digest(ev.CORPUS.read_bytes()) == THRESHOLDS["corpus_sha256"]
    assert ev.render_corpus(ev.build_corpus()) == ev.CORPUS.read_bytes()
    assert len(CORPUS["queries"]) == 40 and {q["kind"] for q in CORPUS["queries"]} == {"dataset", "metric", "dimension"}


def test_every_expected_id_exists_and_is_certified_in_the_catalogue():
    datasets, ontology = set(CORPUS["datasets"]), set(CORPUS["ontology"])
    for q in CORPUS["queries"]:
        assert q["expect"] in (datasets if q["kind"] == "dataset" else ontology)
        if q["kind"] != "dataset":
            assert CORPUS["ontology"][q["expect"]][0] == q["kind"]


def test_the_evaluation_meets_the_proposed_gates():
    report = ev.run_retrieval()
    assert report["ok"] and not report["misses"] and set(report["gates"]) == set(THRESHOLDS["gates"])
    assert report["gates"]["context_token_reduction"]["value"] >= 0.2
    assert THRESHOLDS["approval"]["status"] == "proposed" and report["approval"]["approved_by"] is None


def test_the_adapter_still_holds_when_the_backend_ignores_every_filter():
    report = ev.run_retrieval(client=ev.FakeSearchClient(ignore_filters=True))
    assert (
        report["gates"]["uncertified_or_foreign_results"]["value"] == 0 and report["ok"]
    )  # the adapter re-checks every hit


def test_the_leak_gate_fails_when_the_adapter_stops_rechecking_scope(monkeypatch):
    from app.context.index import OpenSearchContextIndex
    from packages.platform_contracts.context_snapshot import ContextPackItem

    def careless_search(self, query, *, tenant_id, snapshot_id=None, certified_only=True, limit=10):
        hits = self.client._search(
            {
                "size": limit,
                "query": {"bool": {"must": [{"multi_match": {"query": query, "fields": ["text", "asset_id"]}}]}},
            }
        )
        return tuple(
            ContextPackItem(
                asset_id=h["_source"]["asset_id"],
                score=h["_score"],
                text=h["_source"]["text"],
                citation=f"context:{snapshot_id}",
                certified=True,
            )
            for h in hits
        )

    monkeypatch.setattr(OpenSearchContextIndex, "search", careless_search)
    report = ev.run_retrieval(client=ev.FakeSearchClient(ignore_filters=True))
    assert report["gates"]["uncertified_or_foreign_results"]["value"] > 0 and not report["ok"]


def test_a_wrong_expected_answer_lowers_recall_below_the_gate():
    wrong = copy.deepcopy(CORPUS)
    wrong["queries"][0]["expect"] = "employees"
    report = ev.run_retrieval(corpus=wrong)
    assert not report["gates"]["certified_top3_recall"]["meets"] and report["misses"][0]["id"] == "Q001"


def test_a_changed_corpus_file_is_refused_until_the_digest_is_updated(monkeypatch, tmp_path):
    tampered = tmp_path / "corpus.json"
    tampered.write_bytes(ev.CORPUS.read_bytes() + b"\n")
    monkeypatch.setattr(ev, "CORPUS", tampered)
    with pytest.raises(RuntimeError, match="digest"):
        ev.run_retrieval()


def test_lookalike_uncertified_and_other_tenant_assets_are_never_served():
    index, snapshot, _ = ev.build_index(CORPUS)
    for query in ("one row per customer order amount status", "customer region segment signup", "orders ZEBRA-B"):
        items = index.search(query, tenant_id=ev.TENANT, snapshot_id=ev.SNAPSHOT, certified_only=True, limit=10)
        assert items and all(i.certified and "ZEBRA-B" not in i.text and "tb_" not in i.text for i in items)
        assert not {i.asset_id for i in items} & {"orders_draft", "customers_legacy"}
    foreign = index.search("orders", tenant_id=ev.OTHER, snapshot_id=ev.OTHER_SNAPSHOT, certified_only=True)
    assert foreign and all("ZEBRA-B" in i.text for i in foreign)  # the other tenant sees only its own


def test_provenance_and_freshness_gates_can_fail():
    from app.context.quality import evaluate_context_quality

    stale = evaluate_context_quality(ev.build_snapshot(CORPUS, tenant=ev.TENANT, snapshot_id=ev.SNAPSHOT))
    assert not stale.actionable and stale.stale_asset_count == 1 and "stale metadata" in stale.blocking_reasons
    clean = evaluate_context_quality(
        ev.build_snapshot(CORPUS, tenant=ev.TENANT, snapshot_id=ev.SNAPSHOT, with_stale=False)
    )
    assert clean.actionable and clean.provenance_coverage == 1.0
    missing = evaluate_context_quality(
        ev.build_snapshot(CORPUS, tenant=ev.TENANT, snapshot_id=ev.SNAPSHOT, with_stale=False, unversioned=("orders",))
    )
    assert missing.provenance_coverage < 1.0 and "incomplete provenance" in missing.blocking_reasons


def test_the_token_gate_fails_if_the_pack_is_not_smaller_than_the_baseline():
    strict = copy.deepcopy(THRESHOLDS)
    strict["gates"]["context_token_reduction"]["value"] = 0.95
    assert not ev.run_retrieval(thresholds=strict)["gates"]["context_token_reduction"]["meets"]


def test_the_report_states_what_it_does_not_measure():
    text = ev.render_markdown(ev.run_retrieval())
    assert "not BM25" in text and "NOT APPROVED" in text and "real_relevance_ranking" in text
