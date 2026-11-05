"""Product-search evaluation on a synthetic subset built by the real ingest pipeline."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.evaluation.product_search import (
    Bm25Retriever,
    EvalQuery,
    build_report,
    compare_reports,
    evaluate,
    load_queries,
    ndcg_at_k,
    split_queries,
    write_report,
)
from app.evaluation.product_search import (
    main as eval_main,
)
from app.ingest import IngestError, ProductProvenance, ingest, write_subset

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
GAINS = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}
PRODUCT_FIELDS = [
    "product_id",
    "product_locale",
    "product_title",
    "product_description",
    "product_bullet_point",
    "product_brand",
    "product_color",
]
EXAMPLE_FIELDS = ["example_id", "query", "query_id", "product_id", "product_locale", "esci_label", "small_version"]

CATALOG = {
    "P1": "red running shoes",
    "P2": "blue running shoes",
    "P3": "leather office chair",
    "P4": "wireless mouse",
    "P5": "usb keyboard",
    "P6": "stainless water bottle",
}
JUDGMENTS = [  # (query_id, query, product_id, label)
    ("q1", "running shoes", "P1", "E"),
    ("q1", "running shoes", "P2", "E"),
    ("q1", "running shoes", "P6", "I"),
    ("q2", "office chair", "P3", "E"),
    ("q2", "office chair", "P4", "I"),
    ("q3", "wireless mouse", "P4", "E"),
    ("q3", "wireless mouse", "P5", "S"),
    ("q4", "water bottle", "P6", "E"),
    ("q4", "water bottle", "P9", "E"),
]


def _csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def built(tmp_path: Path) -> tuple[Path, Path]:
    products = _csv(
        tmp_path / "p.csv",
        PRODUCT_FIELDS,
        [
            {
                "product_id": pid,
                "product_locale": "us",
                "product_title": title,
                "product_description": "",
                "product_bullet_point": "",
                "product_brand": "Acme",
                "product_color": "",
            }
            for pid, title in CATALOG.items()
        ],
    )
    examples = _csv(
        tmp_path / "e.csv",
        EXAMPLE_FIELDS,
        [
            {
                "example_id": f"e{i}",
                "query": q,
                "query_id": qid,
                "product_id": pid,
                "product_locale": "us",
                "esci_label": label,
                "small_version": "1",
            }
            for i, (qid, q, pid, label) in enumerate(JUDGMENTS)
        ],
    )
    provenance = ProductProvenance(dataset="fixture", dataset_version="t", citation="synthetic", synthetic=True)
    subset = tmp_path / "subset"
    write_subset(ingest(products, examples, provenance=provenance, limit=100, now=NOW), subset)
    return subset, examples


def test_ndcg_rewards_order_and_graded_labels() -> None:
    judged = {"A": "E", "B": "S", "C": "I"}
    assert ndcg_at_k(["A", "B", "C"], judged, GAINS, 3) == pytest.approx(1.0)
    assert ndcg_at_k(["B", "A", "C"], judged, GAINS, 3) < 1.0
    assert ndcg_at_k(["C"], judged, GAINS, 3) == 0.0
    assert ndcg_at_k(["A", "A", "A"], judged, GAINS, 3) < 1.0  # duplicates do not inflate the score
    assert ndcg_at_k(["Z"], {"Z": "I"}, GAINS, 3) == 0.0  # no relevant items: defined as 0, not an error
    with pytest.raises(ValueError):
        ndcg_at_k([], judged, GAINS, 0)


def test_judgments_are_restricted_to_the_subset_and_counted(built: tuple[Path, Path]) -> None:
    queries, dropped = load_queries(built[1], set(CATALOG))
    assert dropped["judgments_outside_subset"] == 1  # P9 is not in the catalog
    by_id = {q.query_id: q for q in queries}
    assert set(by_id["q1"].judgments) == {"P1", "P2", "P6"}
    assert "P9" not in by_id["q4"].judgments


def test_queries_without_a_relevant_product_in_subset_are_dropped_and_counted(tmp_path: Path) -> None:
    examples = _csv(
        tmp_path / "e.csv",
        EXAMPLE_FIELDS,
        [
            {
                "example_id": "1",
                "query": "x",
                "query_id": "q",
                "product_id": "P1",
                "product_locale": "us",
                "esci_label": "I",
                "small_version": "1",
            },
        ],
    )
    queries, dropped = load_queries(examples, {"P1"})
    assert queries == [] and dropped["queries_without_relevant_in_subset"] == 1


def test_conflicting_labels_for_a_pair_are_dropped(tmp_path: Path) -> None:
    rows = [
        {
            "example_id": "1",
            "query": "x",
            "query_id": "q",
            "product_id": "P1",
            "product_locale": "us",
            "esci_label": "E",
            "small_version": "1",
        },
        {
            "example_id": "2",
            "query": "x",
            "query_id": "q",
            "product_id": "P1",
            "product_locale": "us",
            "esci_label": "I",
            "small_version": "1",
        },
        {
            "example_id": "3",
            "query": "x",
            "query_id": "q",
            "product_id": "P2",
            "product_locale": "us",
            "esci_label": "E",
            "small_version": "1",
        },
    ]
    queries, dropped = load_queries(_csv(tmp_path / "e.csv", EXAMPLE_FIELDS, rows), {"P1", "P2"})
    assert dropped["conflicting_pairs_dropped"] == 1 and set(queries[0].judgments) == {"P2"}


def test_split_is_deterministic_disjoint_and_complete() -> None:
    queries = [EvalQuery(f"q{n}", "t", {"P": "E"}) for n in range(200)]
    dev, held = split_queries(queries, seed=7, held_out_fraction=0.3)
    again = split_queries(queries, seed=7, held_out_fraction=0.3)
    assert [q.query_id for q in held] == [q.query_id for q in again[1]]
    assert not {q.query_id for q in dev} & {q.query_id for q in held}
    assert len(dev) + len(held) == 200 and 40 < len(held) < 80
    assert {q.query_id for q in split_queries(queries, seed=8)[1]} != {q.query_id for q in held}
    with pytest.raises(ValueError):
        split_queries(queries, seed=7, held_out_fraction=1.0)


def test_bm25_finds_the_obvious_products(built: tuple[Path, Path]) -> None:
    records = [
        __import__("app.ingest", fromlist=["ProductRecord"]).ProductRecord.model_validate_json(line)
        for line in (built[0] / "products.jsonl").read_text().splitlines()
    ]
    retriever = Bm25Retriever(records)
    assert set(retriever("running shoes", 2)) == {"P1", "P2"}
    assert retriever("zzzz nothing", 5) == []
    assert retriever("running shoes", 5) == retriever("running shoes", 5)


def test_evaluate_reports_consistency_label_mix_and_worst_queries() -> None:
    queries = [EvalQuery("a", "qa", {"P1": "E", "P2": "I"}), EvalQuery("b", "qb", {"P3": "E"})]
    ranks = {"qa": ["P1", "P2"], "qb": ["P9", "P3"]}
    stable = evaluate(lambda text, k: ranks[text][:k], queries, k=2, repeats=3)
    assert stable["consistent_across_repeats"] is True
    assert stable["top_k_label_share"]["unjudged"] == pytest.approx(0.25)
    assert stable["worst_queries"][0]["query_id"] == "b"
    assert stable["exact_recall_at_k"] == pytest.approx(1.0)
    counter = {"n": 0}

    def flaky(text: str, k: int) -> list[str]:
        counter["n"] += 1
        return ["P1", "P2"] if counter["n"] % 2 else ["P2", "P1"]

    assert evaluate(flaky, queries[:1], k=2, repeats=3)["consistent_across_repeats"] is False
    with pytest.raises(ValueError):
        evaluate(flaky, queries, repeats=0)


def test_compare_reports_flags_regressions() -> None:
    base = {"ndcg_at_k": {"mean": 0.8}, "worst_queries": [{"query_id": "a", "ndcg_at_k": 0.4}]}
    worse = {"ndcg_at_k": {"mean": 0.7}, "worst_queries": [{"query_id": "a", "ndcg_at_k": 0.2}]}
    assert len(compare_reports(base, worse)) == 2
    assert compare_reports(base, base) == []


def test_report_is_held_out_first_json_with_caveats(built: tuple[Path, Path], tmp_path: Path) -> None:
    report = build_report(built[0], built[1], seed=1, held_out_fraction=0.5, now=NOW)
    assert report["report_version"] == "product-eval-v1"
    assert report["dataset"]["license_status"] == "unconfirmed"
    assert report["split"]["held_out_queries"] >= 1
    assert any("held_out" in line for line in report["caveats"])
    out = tmp_path / "report.json"
    write_report(report, out)
    assert json.loads(out.read_text())["subset_checksum"] == report["subset_checksum"]
    with pytest.raises(IngestError, match="already exists"):
        write_report(report, out)


def test_report_refuses_a_drifted_subset(built: tuple[Path, Path]) -> None:
    path = built[0] / "products.jsonl"
    path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(IngestError, match="drift"):
        build_report(built[0], built[1])


def test_cli_writes_a_report(built: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "r.json"
    args = ["--subset", str(built[0]), "--examples", str(built[1]), "--out", str(out), "--held-out-fraction", "0.99"]
    assert eval_main(args) == 0
    assert "held_out_queries=" in capsys.readouterr().out and out.exists()
    assert eval_main(args) == 1  # an existing report is never overwritten
