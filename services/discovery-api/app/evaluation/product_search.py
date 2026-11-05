"""Evaluate product search on a built ingest subset using ESCI-style graded judgments.

Design rules (docs/DISCOVERY_ESCI_SCOPE.md, E4): report on held-out queries only for the headline, keep a
separate dev split for tuning, run each retriever more than once and say whether it was consistent, count
judgments that fall outside the subset or are missing, and list the worst queries as a regression set.
Judgments are restricted to the subset so the ideal ranking never contains products the index cannot return.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from app.ingest.models import ProductRecord
from app.ingest.pipeline import IngestError, read_rows, verify_subset

REPORT_VERSION = "product-eval-v1"
# Graded gains by ESCI label. These follow the task's convention as recalled (Exact 1, Substitute 0.1,
# Complement 0.01, Irrelevant 0); confirm against the dataset's documentation before quoting numbers.
DEFAULT_GAINS: Mapping[str, float] = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}
LABELS = ("E", "S", "C", "I")
Retriever = Callable[[str, int], Sequence[str]]


@dataclass(frozen=True)
class EvalQuery:
    query_id: str
    text: str
    judgments: Mapping[str, str]


def load_queries(
    examples_path: Path, product_ids: set[str], *, locale: str = "us"
) -> tuple[list[EvalQuery], dict[str, int]]:
    """Group small-version judgments by query, keeping only products in the subset.

    Returns the queries that have at least one Exact or Substitute product in the subset, plus counts of what
    was dropped. A (query, product) pair with conflicting labels is dropped, not guessed.
    """
    required = ("query_id", "query", "product_id", "product_locale", "esci_label", "small_version")
    texts: dict[str, str] = {}
    labels: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    outside = 0
    for row in read_rows(examples_path, required):
        if row["product_locale"].strip().lower() != locale.lower() or row["small_version"].strip() != "1":
            continue
        label = row["esci_label"].strip().upper()
        if label not in LABELS:
            continue
        pid = row["product_id"].strip()
        if pid not in product_ids:
            outside += 1
            continue
        qid = row["query_id"].strip()
        texts.setdefault(qid, row["query"].strip())
        labels[qid][pid].add(label)
    queries: list[EvalQuery] = []
    conflicts = no_relevant = 0
    for qid in sorted(labels):
        judged: dict[str, str] = {}
        for pid, found in labels[qid].items():
            if len(found) == 1:
                judged[pid] = next(iter(found))
            else:
                conflicts += 1
        if not any(label in ("E", "S") for label in judged.values()):
            no_relevant += 1
            continue
        queries.append(EvalQuery(qid, texts[qid], judged))
    return queries, {
        "judgments_outside_subset": outside,
        "conflicting_pairs_dropped": conflicts,
        "queries_without_relevant_in_subset": no_relevant,
    }


def split_queries(
    queries: Sequence[EvalQuery], *, seed: int, held_out_fraction: float = 0.3
) -> tuple[list[EvalQuery], list[EvalQuery]]:
    """Deterministic dev/held-out partition by hashing ``seed:query_id``; no query lands in both."""
    if not 0.0 < held_out_fraction < 1.0:
        raise ValueError("held_out_fraction must be between 0 and 1")
    dev: list[EvalQuery] = []
    held: list[EvalQuery] = []
    for query in queries:
        bucket = int(hashlib.sha256(f"{seed}:{query.query_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        (held if bucket < held_out_fraction else dev).append(query)
    return dev, held


def ndcg_at_k(ranked: Sequence[str], judgments: Mapping[str, str], gains: Mapping[str, float], k: int) -> float:
    """Graded nDCG where unjudged products count as gain 0 (a conservative reading, reported via judged@k)."""
    if k < 1:
        raise ValueError("k must be at least 1")
    seen: list[str] = []
    for pid in ranked:
        if pid not in seen:
            seen.append(pid)
        if len(seen) == k:
            break
    actual = sum(
        gains.get(judgments.get(pid, "I"), 0.0) / math.log2(rank + 1) for rank, pid in enumerate(seen, start=1)
    )
    ideal_gains = sorted((gains.get(label, 0.0) for label in judgments.values()), reverse=True)[:k]
    ideal = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal_gains, start=1))
    return 0.0 if ideal == 0.0 else actual / ideal


def evaluate(
    retriever: Retriever,
    queries: Sequence[EvalQuery],
    *,
    k: int = 10,
    gains: Mapping[str, float] = DEFAULT_GAINS,
    repeats: int = 3,
    worst: int = 10,
) -> dict[str, object]:
    """Run every query ``repeats`` times and summarize quality, consistency, label mix and the worst queries."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    per_run_ndcg: list[float] = []
    first_rankings: dict[str, tuple[str, ...]] = {}
    consistent = True
    for run in range(repeats):
        scores = []
        for query in queries:
            ranked = tuple(retriever(query.text, k))
            if run == 0:
                first_rankings[query.query_id] = ranked
            elif ranked != first_rankings[query.query_id]:
                consistent = False
            scores.append(ndcg_at_k(ranked, query.judgments, gains, k))
        per_run_ndcg.append(sum(scores) / len(scores) if scores else 0.0)

    per_query = []
    label_counts: Counter[str] = Counter()
    exact_recall: list[float] = []
    judged_share: list[float] = []
    for query in queries:
        top = list(dict.fromkeys(first_rankings[query.query_id]))[:k]
        per_query.append((query.query_id, ndcg_at_k(top, query.judgments, gains, k)))
        for pid in top:
            label_counts[query.judgments.get(pid, "unjudged")] += 1
        exact = {pid for pid, label in query.judgments.items() if label == "E"}
        if exact:
            exact_recall.append(len(exact & set(top)) / len(exact))
        judged_share.append(sum(pid in query.judgments for pid in top) / len(top) if top else 0.0)
    total = sum(label_counts.values())
    mean = lambda values: sum(values) / len(values) if values else 0.0  # noqa: E731
    return {
        "query_count": len(queries),
        "k": k,
        "repeats": repeats,
        "consistent_across_repeats": consistent,
        "ndcg_at_k": {
            "mean": mean(per_run_ndcg),
            "min": min(per_run_ndcg, default=0.0),
            "max": max(per_run_ndcg, default=0.0),
        },
        "exact_recall_at_k": mean(exact_recall),
        "judged_share_at_k": mean(judged_share),
        "top_k_label_share": {
            label: (label_counts[label] / total if total else 0.0) for label in (*LABELS, "unjudged")
        },
        "worst_queries": [
            {"query_id": qid, "ndcg_at_k": score}
            for qid, score in sorted(per_query, key=lambda item: (item[1], item[0]))[:worst]
        ],
    }


def compare_reports(
    baseline: Mapping[str, object], candidate: Mapping[str, object], *, tolerance: float = 0.0
) -> list[str]:
    """Return query ids that were in the baseline's worst list and got worse in the candidate's, plus a mean drop."""
    notes: list[str] = []
    base_mean = baseline["ndcg_at_k"]["mean"]  # type: ignore[index]
    cand_mean = candidate["ndcg_at_k"]["mean"]  # type: ignore[index]
    if cand_mean < base_mean - tolerance:
        notes.append(f"mean ndcg_at_k fell from {base_mean:.4f} to {cand_mean:.4f}")
    base_worst = {item["query_id"]: item["ndcg_at_k"] for item in baseline["worst_queries"]}  # type: ignore[index,union-attr]
    for item in candidate["worst_queries"]:  # type: ignore[union-attr]
        prior = base_worst.get(item["query_id"])
        if prior is not None and item["ndcg_at_k"] < prior - tolerance:
            notes.append(f"query {item['query_id']} regressed from {prior:.4f} to {item['ndcg_at_k']:.4f}")
    return notes


_TOKEN = re.compile(r"[a-z0-9]+")


class Bm25Retriever:
    """A small in-memory BM25 baseline over title, brand, color, bullets and description."""

    def __init__(self, records: Sequence[ProductRecord], *, k1: float = 1.5, b: float = 0.75) -> None:
        self._ids = [record.product_id for record in records]
        self._docs = [
            self._tokens(" ".join((r.title, r.title, r.brand, r.color, r.bullets, r.description))) for r in records
        ]
        self._k1, self._b = k1, b
        self._lengths = [len(doc) for doc in self._docs]
        self._avg = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        self._df: Counter[str] = Counter()
        for doc in self._docs:
            self._df.update(set(doc))
        self._tf = [Counter(doc) for doc in self._docs]

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return _TOKEN.findall(text.lower())

    def __call__(self, query: str, k: int) -> list[str]:
        terms = self._tokens(query)
        n = len(self._ids)
        scored: list[tuple[float, str]] = []
        for index, pid in enumerate(self._ids):
            score = 0.0
            for term in terms:
                freq = self._tf[index].get(term, 0)
                if not freq:
                    continue
                idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                norm = freq + self._k1 * (1 - self._b + self._b * self._lengths[index] / (self._avg or 1.0))
                score += idf * freq * (self._k1 + 1) / norm
            if score > 0.0:
                scored.append((-score, pid))
        scored.sort()
        return [pid for _, pid in scored[:k]]


def build_report(
    subset_dir: Path,
    examples_path: Path,
    retriever_factory: Callable[[Sequence[ProductRecord]], Retriever] = Bm25Retriever,
    *,
    retriever_name: str = "bm25",
    k: int = 10,
    seed: int = 7,
    held_out_fraction: float = 0.3,
    repeats: int = 3,
    now: datetime | None = None,
) -> dict[str, object]:
    """Verify the subset, evaluate dev and held-out splits, and return a JSON-ready report."""
    manifest = verify_subset(subset_dir)
    records = [
        ProductRecord.model_validate_json(line)
        for line in (subset_dir / "products.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    queries, dropped = load_queries(examples_path, {r.product_id for r in records}, locale=manifest.locale)
    dev, held = split_queries(queries, seed=seed, held_out_fraction=held_out_fraction)
    if not held:
        raise IngestError("no held-out queries; the subset has too few judged queries to evaluate")
    retriever = retriever_factory(records)
    return {
        "report_version": REPORT_VERSION,
        "created_at": (now or datetime.now(timezone.utc)).isoformat(),
        "dataset": manifest.provenance.model_dump(mode="json"),
        "subset_checksum": manifest.subset_checksum,
        "subset_size": len(records),
        "locale": manifest.locale,
        "retriever": retriever_name,
        "gains": dict(DEFAULT_GAINS),
        "split": {
            "seed": seed,
            "held_out_fraction": held_out_fraction,
            "dev_queries": len(dev),
            "held_out_queries": len(held),
        },
        "dropped": dropped,
        "held_out": evaluate(retriever, held, k=k, repeats=repeats),
        "dev_for_tuning_only": evaluate(retriever, dev, k=k, repeats=repeats) if dev else None,
        "caveats": [
            "Headline numbers are the held_out block; the dev block is for tuning only.",
            "Unjudged products count as gain 0; judged_share_at_k shows how much of each top-k was judged.",
            "Gains and column names follow the ESCI task as recalled and are unconfirmed against the real files.",
            "Product relevance says nothing about Discovery experience ranking or engagement.",
            "license_status in the dataset block is not an approval to host or redistribute the data.",
        ],
    }


def write_report(report: Mapping[str, object], path: Path) -> None:
    if path.exists():
        raise IngestError(f"{path} already exists; choose a new file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m app.evaluation.product_search")
    parser.add_argument("--subset", type=Path, required=True)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--held-out-fraction", type=float, default=0.3)
    args = parser.parse_args(argv)
    try:
        report = build_report(
            args.subset,
            args.examples,
            k=args.k,
            seed=args.seed,
            repeats=args.repeats,
            held_out_fraction=args.held_out_fraction,
        )
        write_report(report, args.out)
    except (IngestError, ValueError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 1
    held = report["held_out"]
    print(f"held_out_queries={held['query_count']} ndcg_at_{args.k}={held['ndcg_at_k']['mean']:.4f} wrote {args.out}")  # type: ignore[index]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
