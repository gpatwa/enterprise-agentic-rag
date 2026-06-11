#!/usr/bin/env python3
# ruff: noqa: E402,I001
"""
Internal-alpha seed script.

Populates the database with realistic-looking data so a fresh deploy is
demo-ready immediately:

    - Sample threads (5) with a few messages each for the local UI demo user
    - Saved questions (6, two pinned)
    - Glossary terms (4) — ARR, Churn, MQL, NRR
    - One MCP demo connection (github) so the App-connectors UI shows
      "Connected" out of the box. Uses a placeholder PAT — visual demo
      only; real tokens go in via the Sources page when ready.

The script is idempotent: every row is keyed on a stable identifier, so
running it twice doesn't create duplicates. It's also safe to run before
the app has booted (it auto-creates the necessary tables).

Usage
-----
    cd services/api
    DATABASE_URL='postgresql://ragadmin:changeme@localhost:5432/rag_db' \
        MCP_ENCRYPTION_KEY='<fernet key>' \
        DEMO_USER='ui-user' \
        python3 ../../scripts/seed_alpha.py

Or via the Makefile target:

    make seed-alpha
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load .env if available (matches existing seed scripts' convention)
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Build DATABASE_URL from components if not set, matching seed_context_layers.py
if not os.environ.get("DATABASE_URL"):
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "ragadmin")
    password = os.environ.get("DB_PASSWORD", "changeme")
    db = os.environ.get("DB_NAME", "rag_db")
    os.environ["DATABASE_URL"] = (
        f"postgresql://{user}:{password}@{host}:{port}/{db}"
    )

# Add services/api to sys.path so `from app...` works when running from repo root.
api_root = Path(__file__).parent.parent / "services" / "api"
sys.path.insert(0, str(api_root))

import sqlalchemy as sa
from sqlalchemy.orm import Session

# Import models so Base.metadata is populated
from app.memory.postgres import Base, ChatHistory  # noqa: F401
from app.threads.models import Thread, SavedQuestion  # noqa: F401
from app.context.models import Annotation  # noqa: F401
from app.audit.models import AuditLog  # noqa: F401
from app.mcp.models import MCPConnection  # noqa: F401


# Sync URL for seeding (we don't need async overhead here)
SYNC_URL = os.environ["DATABASE_URL"].replace("+asyncpg", "")
TENANT_ID = os.environ.get("DEMO_TENANT_ID", "default")
DEMO_USER = os.environ.get("DEMO_USER", "ui-user")


# ── Sample data ──────────────────────────────────────────────────────


def _utcnow() -> datetime:
    """Naive UTC timestamp for existing timestamp-without-timezone columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


SAMPLE_THREADS = [
    {
        "id": "alpha-thread-revenue",
        "title": "Q3 revenue trends by region",
        "pinned": True,
        "messages": [
            ("user", "What was revenue by region last quarter?"),
            (
                "assistant",
                "Q3 revenue by region: Americas $12.4M (+18% YoY), EMEA $8.9M (+12% YoY), APAC $5.2M (+24% YoY). "
                "APAC growth was led by Singapore and Tokyo expansion. Full SQL attached for verification.",
            ),
            ("user", "What's driving the APAC growth?"),
            (
                "assistant",
                "Three main drivers: (1) two new enterprise contracts in Singapore (combined $1.4M ARR), "
                "(2) Tokyo office hit ramp 6 weeks ahead of plan, (3) Q3 partner-channel deals up 38% YoY in the region.",
            ),
        ],
    },
    {
        "id": "alpha-thread-churn",
        "title": "Customer churn risk this month",
        "pinned": False,
        "messages": [
            ("user", "Which customers are showing churn signals?"),
            (
                "assistant",
                "I identified 14 accounts with elevated churn risk: usage drop > 30% in last 30d AND no logins in 14d AND ≥1 escalated support ticket. "
                "Top 5 by ARR: Acme Logistics ($340K), Globex ($280K), Initech ($240K), Soylent ($220K), Hooli ($190K). "
                "Recommend: assign CSM intervention this week.",
            ),
        ],
    },
    {
        "id": "alpha-thread-incident",
        "title": "Checkout service incident — May 1",
        "pinned": False,
        "messages": [
            (
                "user",
                "What changed in the 4 hours before the May 1 checkout incident?",
            ),
            (
                "assistant",
                "Timeline: 14:32 deploy of payments-service v2.4.1 (PR #4521 by @jordan), "
                "15:18 config change to checkout-redis cluster (max-memory-policy), "
                "15:47 feature flag PAYMENTS_RETRY_BACKOFF flipped to true (50% rollout). "
                "Incident fired at 16:04. Rolling back the config at 16:11 restored health within 2m.",
            ),
        ],
    },
    {
        "id": "alpha-thread-pipeline",
        "title": "Pipeline trends vs last quarter",
        "pinned": False,
        "messages": [
            ("user", "How is the sales pipeline trending vs Q2?"),
            (
                "assistant",
                "Total pipeline: $34.2M (Q3) vs $28.7M (Q2), +19% QoQ. By stage: "
                "Discovery $12.0M (+23%), Proposal $10.0M (+15%), Closing $7.0M (-8%, lower count but +14% avg ACV). "
                "Three deals to watch in Closing: Acme ($1.2M), Globex ($890K), Hooli ($720K).",
            ),
        ],
    },
    {
        "id": "alpha-thread-onboarding",
        "title": "New-hire ramp time YTD",
        "pinned": False,
        "messages": [
            ("user", "How long are new hires taking to ramp this year?"),
            (
                "assistant",
                "Average ramp time YTD: 84 days (down from 102d last year, -18%). "
                "By function: Eng 67d, Sales 91d, GTM 78d. "
                "Drop is correlated with the structured onboarding playbook rolled out in Feb (cohorts before Feb averaged 99d).",
            ),
        ],
    },
]

SAMPLE_SAVED_QUESTIONS = [
    {
        "title": "Daily revenue snapshot",
        "question_text": "What is today's revenue across all regions vs the same day last month?",
        "scope": "data",
        "pinned": True,
        "preview": "$1.42M today, +18% vs same day prior month",
    },
    {
        "title": "Top 10 customers by ARR",
        "question_text": "List my top 10 customers by ARR with their contract end date.",
        "scope": "data",
        "pinned": True,
        "preview": "Acme $1.2M (renews 2026-09-15), Globex $890K, …",
    },
    {
        "title": "Open incidents this week",
        "question_text": "What incidents are open in PagerDuty for the last 7 days?",
        "scope": "auto",
        "pinned": False,
        "preview": "3 open, 1 P1 (checkout-service), 2 P3 (analytics-pipeline retries)",
    },
    {
        "title": "PRs awaiting review > 3 days",
        "question_text": "Show pull requests in payments-service awaiting review for more than 3 days.",
        "scope": "code",
        "pinned": False,
        "preview": "5 PRs older than 3 days; oldest is #4498 (8 days, 2 reviewers requested)",
    },
    {
        "title": "Q3 board metrics",
        "question_text": "Pull the standard board pack metrics for Q3: revenue, ARR, NRR, NDR, gross margin, burn.",
        "scope": "data",
        "pinned": False,
        "preview": "Last run May 1 — see attached PDF",
    },
    {
        "title": "Suspicious admin actions last 24h",
        "question_text": "Surface any admin-role actions on production in the last 24 hours.",
        "scope": "auto",
        "pinned": False,
        "preview": "12 admin actions, none anomalous",
    },
]

GLOSSARY_TERMS = [
    (
        "ARR",
        "Annual Recurring Revenue. Computed as MRR × 12 from active subscriptions; excludes one-time fees, professional services, and overages.",
    ),
    (
        "Churn",
        "Customer cancellation, tracked monthly as both logo churn (count of cancelled customers / total customers) and dollar churn (cancelled ARR / starting ARR).",
    ),
    (
        "MQL",
        "Marketing Qualified Lead — a lead that has met our fit + intent criteria (ICP match + active engagement). Owned by Marketing until SAL handoff.",
    ),
    (
        "NRR",
        "Net Revenue Retention. (Starting MRR + Expansion - Churn - Contraction) / Starting MRR. Best-in-class SaaS targets >120%.",
    ),
]


def main() -> None:
    print(f"[seed-alpha] connecting to {SYNC_URL.split('@')[-1]}")
    engine = sa.create_engine(SYNC_URL)
    # Make sure all tables exist before we touch them.
    Base.metadata.create_all(engine)

    counts = {
        "threads": 0,
        "messages": 0,
        "saved_questions": 0,
        "glossary": 0,
        "mcp_connection": 0,
    }

    with Session(engine) as session:
        _seed_threads_and_messages(session, counts)
        _seed_saved_questions(session, counts)
        _seed_glossary(session, counts)
        _seed_mcp_demo_connection(session, counts)
        session.commit()

    print()
    print("[seed-alpha] summary:")
    for k, v in counts.items():
        print(f"  - {k}: {v}")
    print()
    print(
        "[seed-alpha] tip: visit /sources to see the demo App-connectors tile, "
        "and / to see the seeded threads on the home page."
    )


def _seed_threads_and_messages(session: Session, counts: dict) -> None:
    """One Thread per fixture + one ChatHistory row per message."""
    base_time = _utcnow() - timedelta(hours=72)
    for i, t in enumerate(SAMPLE_THREADS):
        thread = session.get(Thread, t["id"])
        if thread is None:
            thread = Thread(
                id=t["id"],
                tenant_id=TENANT_ID,
                user_id=DEMO_USER,
                title=t["title"],
                pinned=t["pinned"],
                message_count=len(t["messages"]),
                created_at=base_time + timedelta(hours=i * 2),
                updated_at=base_time + timedelta(hours=i * 2 + 1),
            )
            session.add(thread)
            counts["threads"] += 1
        else:
            thread.tenant_id = TENANT_ID
            thread.user_id = DEMO_USER
            thread.title = t["title"]
            thread.pinned = t["pinned"]
            thread.message_count = len(t["messages"])

        # Wipe and re-seed the messages for idempotency. Cheaper than diffing.
        session.execute(
            sa.delete(ChatHistory).where(ChatHistory.session_id == t["id"])
        )
        for j, (role, content) in enumerate(t["messages"]):
            session.add(
                ChatHistory(
                    session_id=t["id"],
                    user_id=DEMO_USER,
                    tenant_id=TENANT_ID,
                    role=role,
                    content=content,
                    created_at=base_time + timedelta(hours=i * 2, minutes=j * 3),
                    metadata_={"seeded": True},
                )
            )
            counts["messages"] += 1


def _seed_saved_questions(session: Session, counts: dict) -> None:
    """Upsert by (tenant_id, user_id, title)."""
    for q in SAMPLE_SAVED_QUESTIONS:
        stmt = sa.select(SavedQuestion).where(
            SavedQuestion.tenant_id == TENANT_ID,
            SavedQuestion.user_id == DEMO_USER,
            SavedQuestion.title == q["title"],
        )
        existing = session.execute(stmt).scalars().first()
        if existing is None:
            session.add(
                SavedQuestion(
                    tenant_id=TENANT_ID,
                    user_id=DEMO_USER,
                    title=q["title"],
                    question_text=q["question_text"],
                    scope=q["scope"],
                    pinned=q["pinned"],
                    last_result_preview=q["preview"],
                    last_run_at=_utcnow() - timedelta(hours=4),
                )
            )
            counts["saved_questions"] += 1
        else:
            existing.question_text = q["question_text"]
            existing.pinned = q["pinned"]
            existing.last_result_preview = q["preview"]


def _seed_glossary(session: Session, counts: dict) -> None:
    """Upsert glossary annotations by key."""
    for key, value in GLOSSARY_TERMS:
        stmt = sa.select(Annotation).where(
            Annotation.tenant_id == TENANT_ID,
            Annotation.annotation_type == "glossary",
            Annotation.key == key,
        )
        existing = session.execute(stmt).scalars().first()
        if existing is None:
            session.add(
                Annotation(
                    tenant_id=TENANT_ID,
                    annotation_type="glossary",
                    key=key,
                    value=value,
                    created_by=DEMO_USER,
                )
            )
            counts["glossary"] += 1
        else:
            existing.value = value


def _seed_mcp_demo_connection(session: Session, counts: dict) -> None:
    """
    One github MCPConnection so the Sources page shows a "Connected" tile.

    Uses a placeholder token — the connector spawns + lists tools fine
    (since the npm server lazy-validates auth at first tool call). Real
    tokens get plugged in via the Sources page when ready.

    Skips silently if MCP_ENCRYPTION_KEY isn't set; the rest of the seed
    is still useful without MCP.
    """
    key = os.environ.get("MCP_ENCRYPTION_KEY")
    if not key:
        print(
            "[seed-alpha] MCP_ENCRYPTION_KEY unset — skipping MCP demo connection"
        )
        return

    from app.mcp.crypto import init_cipher, get_cipher, reset_cipher
    from app.mcp.types import MCPConnectionStatus

    reset_cipher()
    init_cipher(key)

    existing = session.execute(
        sa.select(MCPConnection).where(
            MCPConnection.tenant_id == TENANT_ID,
            MCPConnection.server_name == "github",
        )
    ).scalars().first()

    encrypted = get_cipher().encrypt(
        {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_placeholder_for_alpha_demo"}
    )

    if existing is None:
        session.add(
            MCPConnection(
                tenant_id=TENANT_ID,
                server_name="github",
                status=MCPConnectionStatus.ENABLED.value,
                encrypted_config=encrypted,
                last_health_check=_utcnow(),
                error_message=None,
            )
        )
        counts["mcp_connection"] += 1
    else:
        existing.status = MCPConnectionStatus.ENABLED.value
        existing.encrypted_config = encrypted
        existing.last_health_check = _utcnow()
        existing.error_message = None


if __name__ == "__main__":
    main()
