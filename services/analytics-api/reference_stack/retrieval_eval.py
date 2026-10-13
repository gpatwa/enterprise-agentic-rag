"""ADS-072: context and ontology retrieval, provenance, freshness, and token-efficiency evaluation (fakes only).

The retrieval corpus (a tenant catalogue with lookalike and stale distractors, a second tenant with same-named assets, and 40
hand-written queries) is indexed through the real `OpenSearchContextIndex` adapter into an in-memory stand-in for OpenSearch. The
stand-in scores by term overlap and applies the adapter's `term`/`terms`/`must_not` filters; it is NOT BM25 and has no analyzers or
embeddings, so recall here shows the adapter, the filters, and the pack builder work, not that real relevance ranking does.
Thresholds are PROPOSED until the user approves them.
"""

from __future__ import annotations

import hashlib
import json
import json as _json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.context.index import OpenSearchContextIndex
from app.context.quality import evaluate_context_quality
from packages.platform_contracts.context_snapshot import ContextPackItem, ContextSnapshot, build_context_pack
from packages.platform_contracts.metadata import MetadataAsset, MetadataColumn, MetadataFreshness
from packages.platform_contracts.ontology import OntologyEdge, OntologyNode, OntologyProvenance, OntologySnapshot

HERE = Path(__file__).parent / "m7"
CORPUS = HERE / "retrieval-corpus-v1.json"
THRESHOLDS = HERE / "retrieval-thresholds.proposed.json"
SUITE_VERSION = "m7-retrieval-v1"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
TENANT, OTHER = "tenant-a", "tenant-b"
SNAPSHOT, OTHER_SNAPSHOT = "snap-a-1", "snap-b-1"
_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
STOP = frozenset("the a an of by for and per to in on is are what how do we our me show give i can you total".split())

# id: (display name, physical name, description, columns)
DATASETS = {
    "orders": (
        "Orders",
        "sales_orders",
        "One row per customer order with amount, status, and order date",
        "order_id amount status created_at",
    ),
    "order_items": (
        "Order items",
        "sales_order_items",
        "Line items within an order, with product and quantity",
        "order_id product_id quantity unit_price",
    ),
    "customers": (
        "Customers",
        "crm_customers",
        "One row per customer with signup date, region, and segment",
        "customer_id signup_date region segment",
    ),
    "products": (
        "Products",
        "catalog_products",
        "Product catalogue with category, brand, and list price",
        "product_id category brand list_price",
    ),
    "payments": (
        "Payments",
        "finance_payments",
        "Payments received per order, with method and settlement date",
        "payment_id method settled_at",
    ),
    "refunds": (
        "Refunds",
        "finance_refunds",
        "Refunds issued against orders, with reason and amount",
        "refund_id reason refund_amount",
    ),
    "shipments": (
        "Shipments",
        "logistics_shipments",
        "Shipment events with carrier, dispatch date, and delivery date",
        "shipment_id carrier dispatched_at delivered_at",
    ),
    "inventory": (
        "Inventory levels",
        "warehouse_inventory",
        "Stock on hand by product and warehouse",
        "product_id warehouse stock_on_hand",
    ),
    "web_sessions": (
        "Web sessions",
        "web_sessions",
        "Website visits with acquisition channel, device, and landing page",
        "session_id channel device landing_page",
    ),
    "marketing_spend": (
        "Marketing spend",
        "marketing_spend",
        "Daily advertising spend by campaign and channel",
        "campaign channel spend day",
    ),
    "support_tickets": (
        "Support tickets",
        "support_tickets",
        "Customer support tickets with priority, topic, and resolution time",
        "ticket_id priority topic resolution_hours",
    ),
    "employees": (
        "Employees",
        "hr_employees",
        "Employee roster with department and hire date",
        "employee_id department hired_at",
    ),
}
DISTRACTORS_UNCERTIFIED = {
    "orders_draft": (
        "Orders draft copy",
        "scratch_orders_draft",
        "One row per customer order with amount, status, and order date (work in progress copy)",
        "order_id amount status",
    ),
    "customers_legacy": (
        "Customers legacy",
        "legacy_customers",
        "One row per customer with signup date, region, and segment (old system)",
        "customer_id region",
    ),
}
STALE = {
    "pricing_history": (
        "Pricing history",
        "catalog_pricing_history",
        "Historic list price changes by product",
        "product_id price effective_from",
    )
}
# id: (type, label, aliases, description)
ONTOLOGY = {
    "revenue": ("metric", "Revenue", ["sales", "turnover", "net sales"], "Sum of order amounts"),
    "order_count": ("metric", "Order count", ["number of orders", "orders placed"], "Count of orders"),
    "average_order_value": ("metric", "Average order value", ["AOV", "basket size"], "Mean amount per order"),
    "refund_rate": ("metric", "Refund rate", ["returns rate", "share refunded"], "Refunded amount over revenue"),
    "units_sold": ("metric", "Units sold", ["items sold", "quantity sold"], "Sum of line item quantities"),
    "ad_spend": ("metric", "Advertising spend", ["marketing cost", "campaign spend"], "Sum of daily advertising spend"),
    "ticket_count": ("metric", "Ticket count", ["support volume", "tickets opened"], "Count of support tickets"),
    "resolution_time": (
        "metric",
        "Resolution time",
        ["time to resolve", "ticket handling time"],
        "Mean hours to resolve a ticket",
    ),
    "stock_on_hand": ("metric", "Stock on hand", ["inventory level", "units in warehouse"], "Units currently in stock"),
    "delivery_days": (
        "metric",
        "Delivery days",
        ["shipping time", "delivery lead time"],
        "Days from dispatch to delivery",
    ),
    "region": ("dimension", "Region", ["geography", "customer location"], "Customer region"),
    "customer_segment": ("dimension", "Customer segment", ["audience", "cohort"], "Customer segment"),
    "product_category": (
        "dimension",
        "Product category",
        ["department of goods", "merchandise group"],
        "Product category",
    ),
    "channel": ("dimension", "Acquisition channel", ["traffic source", "marketing channel"], "How the visit arrived"),
    "carrier": ("dimension", "Shipping carrier", ["courier", "delivery company"], "Shipment carrier"),
}
CONTAINS = {
    "orders": ["revenue", "order_count", "average_order_value"],
    "refunds": ["refund_rate"],
    "order_items": ["units_sold"],
}

# (query, kind, expected id)
QUERIES = [
    ("which table has one row per customer order", "dataset", "orders"),
    ("order line items with product and quantity", "dataset", "order_items"),
    ("customer signup date and segment", "dataset", "customers"),
    ("product catalogue brand and list price", "dataset", "products"),
    ("payments received by method", "dataset", "payments"),
    ("refund reasons and amounts", "dataset", "refunds"),
    ("carrier dispatch and delivery dates", "dataset", "shipments"),
    ("stock on hand by warehouse", "dataset", "inventory"),
    ("website visits by device and landing page", "dataset", "web_sessions"),
    ("daily advertising spend by campaign", "dataset", "marketing_spend"),
    ("support tickets by priority and topic", "dataset", "support_tickets"),
    ("employee roster by department", "dataset", "employees"),
    ("where are orders stored", "dataset", "orders"),
    ("settlement date for payments", "dataset", "payments"),
    ("which warehouse holds each product", "dataset", "inventory"),
    ("campaign and channel spend per day", "dataset", "marketing_spend"),
    ("customer region", "dataset", "customers"),
    ("hire date of staff by department", "dataset", "employees"),
    ("ticket resolution hours", "dataset", "support_tickets"),
    ("refund amount against orders", "dataset", "refunds"),
    ("sales", "metric", "revenue"),
    ("turnover", "metric", "revenue"),
    ("number of orders", "metric", "order_count"),
    ("AOV", "metric", "average_order_value"),
    ("returns rate", "metric", "refund_rate"),
    ("quantity sold", "metric", "units_sold"),
    ("marketing cost", "metric", "ad_spend"),
    ("support volume", "metric", "ticket_count"),
    ("time to resolve", "metric", "resolution_time"),
    ("inventory level", "metric", "stock_on_hand"),
    ("shipping time", "metric", "delivery_days"),
    ("net sales", "metric", "revenue"),
    ("customer location", "dimension", "region"),
    ("cohort", "dimension", "customer_segment"),
    ("merchandise group", "dimension", "product_category"),
    ("traffic source", "dimension", "channel"),
    ("courier", "dimension", "carrier"),
    ("marketing channel", "dimension", "channel"),
    ("audience", "dimension", "customer_segment"),
    ("geography", "dimension", "region"),
]

GATE_PLAN = {
    "certified_top3_recall": "Certified dataset/metric top-3 recall >= 98%",
    "uncertified_or_foreign_results": "Uncertified or other-tenant results served: 0 (provider-owned filters)",
    "provenance_coverage": "Provenance on every served asset: 100%",
    "stale_detection_recall": "Stale assets detected by the freshness gate: 100%",
    "context_token_reduction": "Context tokens per successful intent: baseline -20%",
    "pack_budget_overruns": "Packs over their token budget: 0",
}


def build_corpus() -> dict[str, Any]:
    return {
        "suite_version": SUITE_VERSION,
        "note": "Catalogue, ontology, and queries for ADS-072; hand-written. Expected ids are the certified asset a person would pick.",
        "tenant": TENANT,
        "other_tenant": OTHER,
        "datasets": {k: list(v) for k, v in DATASETS.items()},
        "uncertified_lookalikes": {k: list(v) for k, v in DISTRACTORS_UNCERTIFIED.items()},
        "stale": {k: list(v) for k, v in STALE.items()},
        "ontology": {k: [v[0], v[1], v[2], v[3]] for k, v in ONTOLOGY.items()},
        "contains": CONTAINS,
        "queries": [
            {"id": f"Q{i + 1:03d}", "query": q, "kind": kind, "expect": expect}
            for i, (q, kind, expect) in enumerate(QUERIES)
        ],
    }


def render_corpus(corpus: dict[str, Any]) -> bytes:
    return (json.dumps(corpus, indent=1) + "\n").encode()


def corpus_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---- an in-memory stand-in for OpenSearch (term overlap, not BM25) ----


class _Response:
    def __init__(self, payload: dict | None = None, status_code: int = 200) -> None:
        self._payload, self.status_code = payload or {}, status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


class FakeSearchClient:
    def __init__(self, *, ignore_filters: bool = False) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.ignore_filters = ignore_filters  # a deliberately broken backend, to prove the evaluation catches leaks

    def head(self, url):
        return _Response(status_code=200 if self.docs else 404)

    def put(self, url, *, json=None):
        return _Response()

    def post(self, url, *, json=None, content=None, headers=None):
        if url.endswith("/_bulk"):
            lines = [line for line in (content or "").split("\n") if line]
            for action, source in zip(lines[::2], lines[1::2], strict=True):
                self.docs[_json.loads(action)["index"]["_id"]] = _json.loads(source)
            return _Response({"errors": False})
        return _Response({"hits": {"hits": self._search(json or {})}})

    def _matches(self, doc: dict, clause: dict) -> bool:
        if "term" in clause:
            ((field, value),) = clause["term"].items()
            return doc.get(field) == value
        if "terms" in clause:
            ((field, values),) = clause["terms"].items()
            return doc.get(field) in values
        return True

    def _search(self, body: dict) -> list[dict]:
        boolean = body["query"]["bool"]
        multi = boolean["must"][0]["multi_match"]
        weights = {f.split("^")[0]: float(f.split("^")[1]) if "^" in f else 1.0 for f in multi["fields"]}
        query_terms = set(_terms(multi["query"]))
        hits = []
        for doc_id, doc in sorted(self.docs.items()):
            if not self.ignore_filters:
                if not all(self._matches(doc, c) for c in boolean.get("filter", [])):
                    continue
                if any(self._matches(doc, c) for c in boolean.get("must_not", [])):
                    continue
            score = 0.0
            for field, weight in weights.items():
                score += weight * len(query_terms & set(_terms(str(doc.get(field, "")))))
            if score > 0:
                hits.append({"_id": doc_id, "_score": score, "_source": doc})
        hits.sort(key=lambda h: (-h["_score"], h["_id"]))
        return hits[: body.get("size", 10)]


# ---- snapshots ----


def _provenance(source_id: str) -> OntologyProvenance:
    return OntologyProvenance(
        source_system="retrieval-eval", source_id=source_id, source_version="v1", observed_at=NOW, fingerprint="c" * 64
    )


def _asset(asset_id, spec, *, certified=True, stale=False, source_version="catalogue@v1") -> MetadataAsset:
    display, physical, description, columns = spec
    return MetadataAsset(
        id=asset_id,
        display_name=display,
        physical_name=physical,
        provider="retrieval-eval",
        description=description,
        certified=certified,
        source_version=source_version,
        observed_at=NOW,
        columns=[MetadataColumn(name=name, data_type="string") for name in columns.split()],
        freshness=MetadataFreshness(
            expected_interval_seconds=86_400, stale=True, last_updated_at=NOW - timedelta(days=30)
        )
        if stale
        else None,
    )


def build_snapshot(
    corpus: dict[str, Any], *, tenant: str, snapshot_id: str, with_stale: bool = True, unversioned: tuple[str, ...] = ()
) -> ContextSnapshot:
    specs = {k: tuple(v) for k, v in corpus["datasets"].items()}
    assets = [_asset(k, v, source_version=None if k in unversioned else "catalogue@v1") for k, v in specs.items()]
    assets += [_asset(k, tuple(v), certified=False) for k, v in corpus["uncertified_lookalikes"].items()]
    if with_stale:
        assets += [_asset(k, tuple(v), stale=True) for k, v in corpus["stale"].items()]
    nodes = [
        OntologyNode(
            node_id=k,
            tenant_id=tenant,
            node_type=v[0],
            label=v[1],
            lifecycle="certified",
            valid_from=NOW - timedelta(days=1),
            provenance=(_provenance(k),),
            attributes={"aliases": v[2], "description": v[3]},
        )
        for k, v in corpus["ontology"].items()
    ] + [
        OntologyNode(
            node_id=k,
            tenant_id=tenant,
            node_type="dataset",
            label=specs[k][0],
            lifecycle="certified",
            valid_from=NOW - timedelta(days=1),
            provenance=(_provenance(k),),
        )
        for k in specs
    ]
    edges = tuple(
        OntologyEdge(
            edge_id=f"{ds}-contains-{m}",
            tenant_id=tenant,
            edge_type="contains",
            from_node_id=ds,
            to_node_id=m,
            valid_from=NOW - timedelta(days=1),
            provenance=(_provenance(f"{ds}-{m}"),),
        )
        for ds, metrics in corpus["contains"].items()
        for m in metrics
    )
    return ContextSnapshot.build(
        snapshot_id=snapshot_id,
        tenant_id=tenant,
        source_fingerprints=("d" * 64,),
        metadata_assets=tuple(assets),
        ontology=OntologySnapshot(
            snapshot_id=snapshot_id, tenant_id=tenant, captured_at=NOW, nodes=tuple(nodes), edges=edges
        ),
        created_at=NOW,
    )


def _foreign_snapshot(corpus: dict[str, Any]) -> ContextSnapshot:
    """The second tenant has same-named datasets; a leak would be visible by physical name."""
    foreign = {k: (f"{v[0]} (b)", f"tb_{v[1]}", f"{v[2]} ZEBRA-B", v[3]) for k, v in corpus["datasets"].items()}
    corpus_b = {
        **corpus,
        "datasets": {k: list(v) for k, v in foreign.items()},
        "uncertified_lookalikes": {},
        "stale": {},
    }
    return build_snapshot(corpus_b, tenant=OTHER, snapshot_id=OTHER_SNAPSHOT, with_stale=False)


def build_index(
    corpus: dict[str, Any], *, client: FakeSearchClient | None = None
) -> tuple[OpenSearchContextIndex, ContextSnapshot, FakeSearchClient]:
    client = client or FakeSearchClient()
    index = OpenSearchContextIndex("http://fake", "context", client)
    index.ensure_index()
    snapshot = build_snapshot(corpus, tenant=TENANT, snapshot_id=SNAPSHOT)
    index.index_snapshot(snapshot)
    index.index_snapshot(_foreign_snapshot(corpus))
    return index, snapshot, client


# ---- evaluation ----


def run_retrieval(
    *,
    client: FakeSearchClient | None = None,
    corpus: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = CORPUS.read_bytes()
    thresholds = thresholds or json.loads(THRESHOLDS.read_text())
    if corpus is None:
        if corpus_digest(raw) != thresholds["corpus_sha256"]:
            raise RuntimeError("retrieval corpus changed without updating the pinned digest in the thresholds file")
        corpus = json.loads(raw)
    index, snapshot, _ = build_index(corpus, client=client)
    allowed_assets = {a.id for a in snapshot.metadata_assets if a.certified}
    node_ids = {n.node_id for n in snapshot.ontology.nodes if n.lifecycle == "certified"}
    hits_ok = leaks = 0
    results = []
    baseline_tokens = sum(
        _tokens(a.display_name + " " + (a.description or ""), f"context:{SNAPSHOT}:{a.id}")
        for a in snapshot.metadata_assets
        if a.certified
    )
    pack_tokens: list[int] = []
    overruns = 0
    for q in corpus["queries"]:
        if q["kind"] == "dataset":
            items = index.search(q["query"], tenant_id=TENANT, snapshot_id=SNAPSHOT, certified_only=True, limit=5)
            ids = [i.asset_id for i in items]
            top3 = ids[:3]
            leaks += sum(1 for i in items if i.asset_id not in allowed_assets)
            leaks += sum(1 for i in items if "tb_" in i.text or "ZEBRA-B" in i.text)
            pack = build_context_pack(
                snapshot, tuple(items), query=q["query"], token_budget=4_000, graph_depth=1, max_graph_edges=24
            )
            pack_tokens.append(pack.estimated_tokens)
            overruns += pack.estimated_tokens > pack.token_budget
            leaks += sum(1 for i in pack.items if i.asset_id not in allowed_assets)
        else:
            node_hits = index.search_ontology(
                q["query"],
                tenant_id=TENANT,
                snapshot_id=SNAPSHOT,
                certified_only=True,
                node_types=(q["kind"],),
                limit=5,
            )
            ids = [h.node_id for h in node_hits]
            top3 = ids[:3]
            leaks += sum(1 for h in node_hits if h.node_id not in node_ids)
            pack_items = tuple(
                ContextPackItem(
                    asset_id=h.node_id,
                    score=h.score,
                    text=h.label,
                    citation=h.citation.replace(":ontology:", ":"),
                    certified=True,
                )
                for h in node_hits
            )
            pack_tokens.append(sum(_tokens(i.text, i.citation) for i in pack_items))
        hit = q["expect"] in top3
        hits_ok += hit
        results.append({"id": q["id"], "kind": q["kind"], "expect": q["expect"], "top3": top3, "hit": hit})
    quality = evaluate_context_quality(snapshot)
    stale_expected = len(corpus["stale"])
    clean = evaluate_context_quality(build_snapshot(corpus, tenant=TENANT, snapshot_id=SNAPSHOT, with_stale=False))
    unversioned = evaluate_context_quality(
        build_snapshot(corpus, tenant=TENANT, snapshot_id=SNAPSHOT, unversioned=("orders",))
    )
    mean_pack = sum(pack_tokens) / len(pack_tokens)
    metrics = {
        "certified_top3_recall": hits_ok / len(corpus["queries"]),
        "uncertified_or_foreign_results": leaks,
        "provenance_coverage": clean.provenance_coverage
        if clean.provenance_coverage >= 1.0 and unversioned.provenance_coverage < 1.0
        else 0.0,
        "stale_detection_recall": (quality.stale_asset_count / stale_expected if stale_expected else 1.0)
        if (not quality.actionable and clean.actionable)
        else 0.0,
        "context_token_reduction": 1.0 - mean_pack / baseline_tokens,
        "pack_budget_overruns": overruns,
    }
    gates = {
        name: {
            "value": metrics[name],
            "op": gate["op"],
            "threshold": gate["value"],
            "meets": bool(_OPS[gate["op"]](metrics[name], gate["value"])),
        }
        for name, gate in thresholds["gates"].items()
    }
    return {
        "packet": "ADS-072",
        "suite_version": SUITE_VERSION,
        "corpus_sha256": thresholds["corpus_sha256"],
        "approval": thresholds["approval"],
        "meets_thresholds": all(g["meets"] for g in gates.values()),
        "ok": all(g["meets"] for g in gates.values()),
        "gates": gates,
        "gate_plan": GATE_PLAN,
        "samples": {
            "queries": len(corpus["queries"]),
            "baseline_tokens": baseline_tokens,
            "mean_pack_tokens": mean_pack,
        },
        "not_measured": thresholds["not_measured"],
        "misses": [r for r in results if not r["hit"]],
        "queries": results,
    }


def _tokens(text: str, citation: str) -> int:
    return max(1, (len(text) + len(citation) + 3) // 4)  # the same estimator as build_context_pack


def render_markdown(report: dict[str, Any]) -> str:
    approval = report["approval"]["status"]
    lines = [
        "# ADS-072: Context and Ontology Retrieval, Provenance, Freshness, and Token Efficiency",
        "",
        f"Suite `{report['suite_version']}`, corpus `{report['corpus_sha256'][:12]}`. **Result: "
        f"{'MEETS' if report['ok'] else 'DOES NOT MEET'} the {approval} thresholds.** The thresholds are {approval.upper()}"
        f"{' and NOT APPROVED' if approval != 'approved' else ''}; a pass is not a go/no-go.",
        "",
        "## Scope and limits",
        "",
        "- Indexed through the real `OpenSearchContextIndex` adapter into an in-memory stand-in that scores by term overlap and applies the adapter's filters. It is not BM25 and has no analyzers or embeddings.",
        f"- {report['samples']['queries']} hand-written queries over a 12-dataset catalogue with lookalike, uncertified, stale, and other-tenant distractors.",
        f"- Token baseline is sending the whole certified catalogue ({report['samples']['baseline_tokens']} estimated tokens); mean bounded pack is {report['samples']['mean_pack_tokens']:.0f}.",
        "",
        "## Metrics",
        "",
        "| Metric | Measured | Gate | Meets | Plan gate |",
        "|---|---:|---:|:---:|---|",
    ]
    for name, gate in report["gates"].items():
        value = gate["value"]
        lines.append(
            f"| `{name}` | {value:.4g} | {gate['op']} {gate['threshold']} | {'yes' if gate['meets'] else '**NO**'} | {report['gate_plan'][name]} |"
        )
    lines += ["", "## Misses", ""] + (
        [f"- {m['id']} ({m['kind']}): wanted `{m['expect']}`, got {m['top3']}" for m in report["misses"]] or ["None."]
    )
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)


def write_corpus() -> str:
    HERE.mkdir(exist_ok=True)
    raw = render_corpus(build_corpus())
    CORPUS.write_bytes(raw)
    return corpus_digest(raw)
