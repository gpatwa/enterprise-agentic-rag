#!/usr/bin/env python3
"""
Seed script for Context Layer tables.

Populates all four context layer tables with realistic sample data
for end-to-end testing. Run after `make up` and `make init`.

Usage:
    python3 scripts/seed_context_layers.py

Requires DATABASE_URL or DB_HOST/DB_PASSWORD env vars.
"""
import os
import sys
from datetime import datetime, timedelta

# Load .env if available
from pathlib import Path

env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Build DATABASE_URL from components if not set
if not os.environ.get("DATABASE_URL"):
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "ragadmin")
    password = os.environ.get("DB_PASSWORD", "changeme")
    db = os.environ.get("DB_NAME", "rag_db")
    os.environ["DATABASE_URL"] = f"postgresql://{user}:{password}@{host}:{port}/{db}"

import sqlalchemy as sa
from sqlalchemy.orm import Session

DATABASE_URL = os.environ["DATABASE_URL"].replace("+asyncpg", "")

engine = sa.create_engine(DATABASE_URL)

TENANT_ID = "default"

# ── Layer 1: Document Metadata ─────────────────────────────────────────

DOCUMENT_METADATA = [
    {
        "tenant_id": TENANT_ID,
        "document_id": "doc-quarterly-report-q4",
        "filename": "quarterly_report_q4_2025.pdf",
        "file_type": "pdf",
        "ingested_at": datetime.utcnow() - timedelta(days=5),
        "access_count": 12,
        "freshness_score": 0.96,
        "summary": "Q4 2025 financial results including revenue breakdown by segment, operating margins, and forward guidance.",
        "tags": ["finance", "quarterly-report", "revenue", "2025"],
        "chunk_count": 47,
        "source_url": "",
    },
    {
        "tenant_id": TENANT_ID,
        "document_id": "doc-engineering-runbook",
        "filename": "engineering_runbook.md",
        "file_type": "markdown",
        "ingested_at": datetime.utcnow() - timedelta(days=30),
        "access_count": 8,
        "freshness_score": 0.79,
        "summary": "Engineering runbook covering deployment procedures, incident response, on-call rotation, and escalation paths.",
        "tags": ["engineering", "ops", "runbook", "deployment"],
        "chunk_count": 23,
        "source_url": "",
    },
    {
        "tenant_id": TENANT_ID,
        "document_id": "doc-data-pipeline-arch",
        "filename": "data_pipeline_architecture.pdf",
        "file_type": "pdf",
        "ingested_at": datetime.utcnow() - timedelta(days=60),
        "access_count": 5,
        "freshness_score": 0.63,
        "summary": "Architecture doc for the main ETL pipeline: Kafka ingestion, Spark transformations, Snowflake warehouse loading.",
        "tags": ["data-engineering", "architecture", "etl", "spark", "snowflake"],
        "chunk_count": 31,
        "source_url": "",
    },
    {
        "tenant_id": TENANT_ID,
        "document_id": "doc-customer-onboarding",
        "filename": "customer_onboarding_guide.pdf",
        "file_type": "pdf",
        "ingested_at": datetime.utcnow() - timedelta(days=15),
        "access_count": 20,
        "freshness_score": 0.89,
        "summary": "Step-by-step customer onboarding process including KYC checks, account provisioning, and initial setup.",
        "tags": ["onboarding", "customer-success", "kyc", "process"],
        "chunk_count": 18,
        "source_url": "",
    },
]

# ── Layer 2: Annotations & Glossary ────────────────────────────────────

ANNOTATIONS = [
    # Glossary terms
    {"tenant_id": TENANT_ID, "annotation_type": "glossary", "key": "ARR", "value": "Annual Recurring Revenue — the annualized value of active subscription contracts. Excludes one-time fees and professional services.", "created_by": "admin"},
    {"tenant_id": TENANT_ID, "annotation_type": "glossary", "key": "MRR", "value": "Monthly Recurring Revenue — total predictable revenue normalized to a monthly amount. ARR = MRR × 12.", "created_by": "admin"},
    {"tenant_id": TENANT_ID, "annotation_type": "glossary", "key": "NDR", "value": "Net Dollar Retention — measures revenue expansion/contraction from existing customers. NDR > 100% means expansion exceeds churn.", "created_by": "admin"},
    {"tenant_id": TENANT_ID, "annotation_type": "glossary", "key": "CAC", "value": "Customer Acquisition Cost — total sales & marketing spend divided by new customers acquired in the period.", "created_by": "admin"},
    {"tenant_id": TENANT_ID, "annotation_type": "glossary", "key": "LTV", "value": "Lifetime Value — predicted total revenue from a customer over their entire relationship. LTV:CAC ratio should be > 3:1.", "created_by": "admin"},
    {"tenant_id": TENANT_ID, "annotation_type": "glossary", "key": "DAU", "value": "Daily Active Users — unique users who perform at least one meaningful action per day.", "created_by": "admin"},
    {"tenant_id": TENANT_ID, "annotation_type": "glossary", "key": "churn rate", "value": "Percentage of customers who cancel or downgrade their subscription in a given period. Our target is < 5% annual logo churn.", "created_by": "admin"},

    # KPI definitions
    {"tenant_id": TENANT_ID, "annotation_type": "kpi", "key": "revenue growth", "value": "Quarter-over-quarter revenue growth rate. Target: 15% QoQ for 2025. Calculated as (current_quarter - prev_quarter) / prev_quarter × 100.", "created_by": "admin"},
    {"tenant_id": TENANT_ID, "annotation_type": "kpi", "key": "gross margin", "value": "Gross Margin = (Revenue - COGS) / Revenue. Our target is 72%+ for SaaS and 55%+ for managed services.", "created_by": "admin"},
    {"tenant_id": TENANT_ID, "annotation_type": "kpi", "key": "pipeline coverage", "value": "Ratio of qualified pipeline value to quarterly revenue target. Healthy coverage is 3x-4x. Below 2.5x triggers pipeline generation sprint.", "created_by": "admin"},

    # Descriptions
    {"tenant_id": TENANT_ID, "annotation_type": "description", "key": "data warehouse", "value": "Our primary data warehouse is Snowflake (us-east-1). Contains 3 schemas: raw (landing), staging (cleaned), and analytics (star schema models).", "created_by": "admin"},
    {"tenant_id": TENANT_ID, "annotation_type": "description", "key": "deployment", "value": "Production deployments use blue-green strategy on EKS. Canary releases for API changes. Rollback window is 30 minutes.", "created_by": "admin"},
]

# ── Layer 3: Code & Pipeline Context ───────────────────────────────────

CODE_CONTEXTS = [
    {
        "tenant_id": TENANT_ID,
        "context_type": "etl_pipeline",
        "name": "daily_revenue_pipeline",
        "description": "Daily ETL pipeline that aggregates transaction data from Stripe and Salesforce into the revenue fact table. Runs at 2am UTC via Airflow.",
        "source_code": "SELECT date_trunc('day', t.created_at) as revenue_date, SUM(t.amount) as daily_revenue FROM transactions t GROUP BY 1",
        "lineage": {"upstream": ["stripe_transactions", "salesforce_opportunities"], "downstream": ["revenue_fact", "executive_dashboard"]},
    },
    {
        "tenant_id": TENANT_ID,
        "context_type": "etl_pipeline",
        "name": "customer_health_score",
        "description": "Weekly pipeline computing customer health scores from product usage, support tickets, and NPS survey data. Output feeds the CS team dashboard.",
        "source_code": "",
        "lineage": {"upstream": ["product_events", "zendesk_tickets", "nps_surveys"], "downstream": ["customer_health_fact", "cs_dashboard"]},
    },
    {
        "tenant_id": TENANT_ID,
        "context_type": "sql_query",
        "name": "monthly_churn_analysis",
        "description": "Identifies churned accounts by comparing active subscriptions month-over-month. Accounts missing from current month are flagged as churned.",
        "source_code": "SELECT prev.account_id, prev.plan, prev.mrr FROM subscriptions_prev prev LEFT JOIN subscriptions_curr curr ON prev.account_id = curr.account_id WHERE curr.account_id IS NULL",
        "lineage": {"upstream": ["subscriptions"], "downstream": ["churn_report"]},
    },
    {
        "tenant_id": TENANT_ID,
        "context_type": "api_endpoint",
        "name": "/api/v1/analytics/revenue",
        "description": "REST endpoint returning revenue metrics. Accepts date range, granularity (daily/weekly/monthly), and segment filters. Powers the executive dashboard.",
        "source_code": "",
        "lineage": {"upstream": ["revenue_fact"], "downstream": ["executive_dashboard", "investor_report"]},
    },
    {
        "tenant_id": TENANT_ID,
        "context_type": "data_lineage",
        "name": "stripe_to_warehouse",
        "description": "Data flow from Stripe webhooks through Kafka, Spark streaming job, to Snowflake raw.stripe_events table. Latency target: < 15 minutes.",
        "source_code": "",
        "lineage": {"upstream": ["stripe_webhooks"], "downstream": ["raw.stripe_events", "staging.transactions", "analytics.revenue_fact"]},
    },
]

# ── Layer 4: Business Context & Rules ──────────────────────────────────

BUSINESS_RULES = [
    # Terminology
    {"tenant_id": TENANT_ID, "context_type": "terminology", "key": "enterprise customer", "value": "A customer with ARR > $100K. Enterprise customers get dedicated CSM, priority support SLA (< 1hr response), and quarterly business reviews.", "applies_to_roles": ["all"], "priority": 10},
    {"tenant_id": TENANT_ID, "context_type": "terminology", "key": "SMB customer", "value": "Small/medium business customer with ARR < $100K. Self-serve onboarding, pooled support model, community-tier SLA.", "applies_to_roles": ["all"], "priority": 8},
    {"tenant_id": TENANT_ID, "context_type": "terminology", "key": "expansion revenue", "value": "Additional revenue from existing customers via upsells, cross-sells, or seat additions. Does NOT include price increases from contract renewals.", "applies_to_roles": ["all"], "priority": 9},

    # Business rules
    {"tenant_id": TENANT_ID, "context_type": "business_rule", "key": "revenue recognition", "value": "Revenue is recognized ratably over the subscription term per ASC 606. Multi-year deals are NOT recognized upfront. Professional services revenue is recognized upon delivery.", "applies_to_roles": ["finance", "all"], "priority": 10},
    {"tenant_id": TENANT_ID, "context_type": "business_rule", "key": "discount approval", "value": "Discounts > 20% require VP Sales approval. Discounts > 35% require CRO approval. No discount may exceed 40% without CEO exception.", "applies_to_roles": ["sales", "finance", "all"], "priority": 9},
    {"tenant_id": TENANT_ID, "context_type": "business_rule", "key": "data retention", "value": "Customer data retained for 90 days post-contract termination. PII is purged within 30 days of deletion request per GDPR/CCPA. Logs retained 1 year.", "applies_to_roles": ["engineering", "compliance", "all"], "priority": 10},
    {"tenant_id": TENANT_ID, "context_type": "business_rule", "key": "incident severity", "value": "SEV1: full outage (15min response, all-hands). SEV2: degraded service (30min response, on-call team). SEV3: minor issue (4hr response, next business day fix).", "applies_to_roles": ["engineering", "all"], "priority": 8},

    # Role-specific context
    {"tenant_id": TENANT_ID, "context_type": "role_context", "key": "sales context", "value": "Current quarter target: $12M ARR. Pipeline coverage at 3.2x. Key verticals: fintech, healthcare, e-commerce. Competitive threats: Glean, Guru.", "applies_to_roles": ["sales"], "priority": 7},
    {"tenant_id": TENANT_ID, "context_type": "role_context", "key": "engineering context", "value": "Current sprint focus: platform reliability (99.95% SLA target). Tech debt budget: 20% of sprint capacity. Freeze period: Dec 20 - Jan 5.", "applies_to_roles": ["engineering"], "priority": 7},

    # Org structure
    {"tenant_id": TENANT_ID, "context_type": "org_structure", "key": "data team", "value": "Data team (12 people) reports to VP Engineering. Sub-teams: Data Platform (4), Analytics Engineering (4), ML Engineering (4). Uses dbt + Snowflake + Airflow stack.", "applies_to_roles": ["all"], "priority": 5},
]


def seed():
    """Insert seed data into context layer tables."""
    from sqlalchemy import text

    with engine.begin() as conn:
        # Check if already seeded
        result = conn.execute(text("SELECT COUNT(*) FROM annotations"))
        count = result.scalar()
        if count > 0:
            print(f"⚠️  Tables already have data ({count} annotations). Use --force to re-seed.")
            if "--force" not in sys.argv:
                return

            # Clear existing data
            print("🗑️  Clearing existing context layer data...")
            conn.execute(text("DELETE FROM business_context WHERE tenant_id = :tid"), {"tid": TENANT_ID})
            conn.execute(text("DELETE FROM code_context WHERE tenant_id = :tid"), {"tid": TENANT_ID})
            conn.execute(text("DELETE FROM annotations WHERE tenant_id = :tid"), {"tid": TENANT_ID})
            conn.execute(text("DELETE FROM document_metadata WHERE tenant_id = :tid"), {"tid": TENANT_ID})

        # Seed Layer 1: Document Metadata
        print("📄 Seeding document metadata...")
        for doc in DOCUMENT_METADATA:
            conn.execute(
                text("""
                    INSERT INTO document_metadata
                        (tenant_id, document_id, filename, file_type, ingested_at,
                         access_count, freshness_score, summary, tags, chunk_count, source_url)
                    VALUES
                        (:tenant_id, :document_id, :filename, :file_type, :ingested_at,
                         :access_count, :freshness_score, :summary, :tags, :chunk_count, :source_url)
                """),
                {**doc, "tags": str(doc["tags"]).replace("'", '"')},
            )
        print(f"   ✅ {len(DOCUMENT_METADATA)} documents")

        # Seed Layer 2: Annotations
        print("📖 Seeding annotations & glossary...")
        for ann in ANNOTATIONS:
            conn.execute(
                text("""
                    INSERT INTO annotations (tenant_id, annotation_type, key, value, created_by)
                    VALUES (:tenant_id, :annotation_type, :key, :value, :created_by)
                """),
                ann,
            )
        print(f"   ✅ {len(ANNOTATIONS)} annotations")

        # Seed Layer 3: Code Context
        print("💻 Seeding code & pipeline context...")
        for ctx in CODE_CONTEXTS:
            conn.execute(
                text("""
                    INSERT INTO code_context
                        (tenant_id, context_type, name, description, source_code, lineage)
                    VALUES
                        (:tenant_id, :context_type, :name, :description, :source_code, :lineage)
                """),
                {**ctx, "lineage": str(ctx["lineage"]).replace("'", '"')},
            )
        print(f"   ✅ {len(CODE_CONTEXTS)} code contexts")

        # Seed Layer 4: Business Context
        print("🏢 Seeding business rules & context...")
        for rule in BUSINESS_RULES:
            conn.execute(
                text("""
                    INSERT INTO business_context
                        (tenant_id, context_type, key, value, applies_to_roles, priority)
                    VALUES
                        (:tenant_id, :context_type, :key, :value, :applies_to_roles, :priority)
                """),
                {**rule, "applies_to_roles": str(rule["applies_to_roles"]).replace("'", '"')},
            )
        print(f"   ✅ {len(BUSINESS_RULES)} business rules")

    total = len(DOCUMENT_METADATA) + len(ANNOTATIONS) + len(CODE_CONTEXTS) + len(BUSINESS_RULES)
    print(f"\n🎉 Context layer seeding complete! {total} records inserted.")
    print("\nTo enable context layers, set CONTEXT_LAYERS_ENABLED=true in .env and restart the API server.")


if __name__ == "__main__":
    seed()
