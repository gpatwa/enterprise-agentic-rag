# eval/context_layer_eval.py
"""
Evaluation suite for Context Layer Architecture.

Measures how context enrichment improves answer quality by comparing
RAG responses with and without context layers enabled. Uses the LLM
judge to score answers on a 1-5 scale.

Metrics:
  - Accuracy improvement: does context make answers more precise?
  - Terminology consistency: does the answer use correct business terms?
  - Hallucination reduction: does context reduce fabricated claims?

Usage:
    python3 eval/context_layer_eval.py
"""
import json
import os
import sys
from pathlib import Path
from typing import List, Dict

# ── Evaluation Dataset ─────────────────────────────────────────────────
# Questions that specifically benefit from context layer enrichment.

CONTEXT_EVAL_DATASET = [
    {
        "id": "ctx-01",
        "question": "What is our ARR and how is it calculated?",
        "ground_truth": "ARR (Annual Recurring Revenue) is the annualized value of active subscription contracts, excluding one-time fees and professional services. ARR = MRR × 12.",
        "requires_layers": ["glossary"],
        "category": "terminology",
    },
    {
        "id": "ctx-02",
        "question": "What is our revenue recognition policy?",
        "ground_truth": "Revenue is recognized ratably over the subscription term per ASC 606. Multi-year deals are NOT recognized upfront. Professional services revenue is recognized upon delivery.",
        "requires_layers": ["business_rules"],
        "category": "business_rules",
    },
    {
        "id": "ctx-03",
        "question": "How does the daily revenue pipeline work?",
        "ground_truth": "The daily_revenue_pipeline is an ETL pipeline that aggregates transaction data from Stripe and Salesforce into the revenue fact table. It runs at 2am UTC via Airflow. Upstream sources are stripe_transactions and salesforce_opportunities; downstream feeds revenue_fact and executive_dashboard.",
        "requires_layers": ["code_context"],
        "category": "data_lineage",
    },
    {
        "id": "ctx-04",
        "question": "What defines an enterprise customer vs SMB?",
        "ground_truth": "Enterprise customers have ARR > $100K and get dedicated CSM, priority support SLA (< 1hr response), and quarterly business reviews. SMB customers have ARR < $100K with self-serve onboarding, pooled support, and community-tier SLA.",
        "requires_layers": ["business_rules", "glossary"],
        "category": "terminology",
    },
    {
        "id": "ctx-05",
        "question": "What is the churn rate target and how do we track it?",
        "ground_truth": "Our target is < 5% annual logo churn. The monthly_churn_analysis SQL query identifies churned accounts by comparing active subscriptions month-over-month. Accounts missing from current month are flagged as churned.",
        "requires_layers": ["glossary", "code_context"],
        "category": "kpi",
    },
    {
        "id": "ctx-06",
        "question": "What discount levels require approval?",
        "ground_truth": "Discounts > 20% require VP Sales approval. Discounts > 35% require CRO approval. No discount may exceed 40% without CEO exception.",
        "requires_layers": ["business_rules"],
        "category": "business_rules",
    },
    {
        "id": "ctx-07",
        "question": "How does data flow from Stripe to our warehouse?",
        "ground_truth": "Data flows from Stripe webhooks through Kafka, then a Spark streaming job, to the Snowflake raw.stripe_events table. Latency target is < 15 minutes. Downstream tables include staging.transactions and analytics.revenue_fact.",
        "requires_layers": ["code_context"],
        "category": "data_lineage",
    },
    {
        "id": "ctx-08",
        "question": "What is NDR and why does it matter?",
        "ground_truth": "NDR (Net Dollar Retention) measures revenue expansion/contraction from existing customers. NDR > 100% means expansion exceeds churn, indicating healthy growth without relying solely on new customer acquisition.",
        "requires_layers": ["glossary"],
        "category": "terminology",
    },
    {
        "id": "ctx-09",
        "question": "What is the incident severity classification?",
        "ground_truth": "SEV1: full outage (15min response, all-hands). SEV2: degraded service (30min response, on-call team). SEV3: minor issue (4hr response, next business day fix).",
        "requires_layers": ["business_rules"],
        "category": "business_rules",
    },
    {
        "id": "ctx-10",
        "question": "What is pipeline coverage and what's a healthy ratio?",
        "ground_truth": "Pipeline coverage is the ratio of qualified pipeline value to quarterly revenue target. Healthy coverage is 3x-4x. Below 2.5x triggers a pipeline generation sprint.",
        "requires_layers": ["glossary"],
        "category": "kpi",
    },
]


# ── Evaluation Logic ───────────────────────────────────────────────────


def build_eval_report(
    results_with_context: List[Dict],
    results_without_context: List[Dict],
) -> Dict:
    """
    Compare answer quality with and without context layers.

    Each result dict: {"id", "question", "system_answer", "score", "reasoning"}
    """
    improvements = []
    for with_ctx, without_ctx in zip(results_with_context, results_without_context):
        delta = with_ctx["score"] - without_ctx["score"]
        improvements.append({
            "id": with_ctx["id"],
            "question": with_ctx["question"],
            "score_with_context": with_ctx["score"],
            "score_without_context": without_ctx["score"],
            "improvement": delta,
            "reasoning_with": with_ctx["reasoning"],
            "reasoning_without": without_ctx["reasoning"],
        })

    avg_with = sum(r["score_with_context"] for r in improvements) / len(improvements)
    avg_without = sum(r["score_without_context"] for r in improvements) / len(improvements)

    by_category = {}
    for item in CONTEXT_EVAL_DATASET:
        cat = item["category"]
        matching = [i for i in improvements if i["id"] == item["id"]]
        if matching:
            by_category.setdefault(cat, []).append(matching[0]["improvement"])

    category_summary = {
        cat: {
            "avg_improvement": sum(vals) / len(vals),
            "count": len(vals),
        }
        for cat, vals in by_category.items()
    }

    return {
        "total_questions": len(improvements),
        "avg_score_with_context": round(avg_with, 2),
        "avg_score_without_context": round(avg_without, 2),
        "avg_improvement": round(avg_with - avg_without, 2),
        "category_breakdown": category_summary,
        "details": improvements,
    }


def simulate_eval():
    """
    Run a simulated evaluation using the dataset.

    In production, this would:
    1. Call the RAG API with CONTEXT_LAYERS_ENABLED=false, collect answers
    2. Call the RAG API with CONTEXT_LAYERS_ENABLED=true, collect answers
    3. Run LLM judge on both sets
    4. Generate comparison report

    For now, produces the dataset structure and scoring rubric.
    """
    print("=" * 60)
    print("Context Layer Evaluation Suite")
    print("=" * 60)

    print(f"\n📋 Dataset: {len(CONTEXT_EVAL_DATASET)} evaluation questions")
    print("\nCategories:")
    categories = {}
    for item in CONTEXT_EVAL_DATASET:
        categories.setdefault(item["category"], 0)
        categories[item["category"]] += 1
    for cat, count in categories.items():
        print(f"  - {cat}: {count} questions")

    print("\nRequired context layers per question:")
    for item in CONTEXT_EVAL_DATASET:
        layers = ", ".join(item["requires_layers"])
        print(f"  [{item['id']}] {item['question'][:60]}... → {layers}")

    # Save dataset for external use
    output_dir = Path(__file__).parent / "datasets"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "context_layer_eval.json"
    with open(output_path, "w") as f:
        json.dump(CONTEXT_EVAL_DATASET, f, indent=2)
    print(f"\n💾 Dataset saved to {output_path}")

    print("\n" + "=" * 60)
    print("To run full evaluation:")
    print("  1. Start API: make dev")
    print("  2. Seed context: python3 scripts/seed_context_layers.py")
    print("  3. Set CONTEXT_LAYERS_ENABLED=true in .env")
    print("  4. Run: python3 eval/context_layer_eval.py --live")
    print("=" * 60)


if __name__ == "__main__":
    if "--live" in sys.argv:
        print("Live evaluation requires a running API server.")
        print("Use the RAG API client to collect answers, then pass to build_eval_report().")
    else:
        simulate_eval()
