# services/api/app/analytics/engine.py
"""
Data Analytics Engine — SQL generation + execution.

Orchestrates:
1. Schema context assembly (relevant tables/columns for the query)
2. LLM-based SQL generation
3. SQL safety validation
4. Read-only query execution with timeout
5. Result formatting
"""
import asyncio
import logging
import re
import time
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import text

from app.analytics.safety import check_cost_guard, sanitize_result, validate_sql
from app.analytics.schema_context import build_schema_prompt
from app.config import settings

logger = logging.getLogger(__name__)

# Module-level engine — initialized once at startup
_engine: Optional[sa.engine.Engine] = None


# ── SQL Generation Prompt ─────────────────────────────────────────────

_SQL_SYSTEM_PROMPT = """You are an expert PostgreSQL analyst for an e-commerce company (Brazilian marketplace, Olist dataset).

Given the database schema below, write a single PostgreSQL SELECT query to answer the user's question.

Rules:
- Output ONLY the SQL query, no explanation, no markdown fences, no comments.
- Use proper JOINs — always join through order_id as the central key.
- For revenue, use: SUM(olist_order_payments.payment_value)
- For time analysis, use: olist_orders.order_purchase_timestamp
- Use DATE_TRUNC() for grouping by month/quarter/year.
- Always add ORDER BY for sorted results.
- Add LIMIT 100 unless the user asks for all data.
- Use table aliases for readability (o for orders, oi for order_items, etc.).
- Product categories are in Portuguese — use them as-is.
- Filter for order_status = 'delivered' when calculating revenue or delivery metrics.

{schema}
"""


# ── Public API ────────────────────────────────────────────────────────

def init_analytics_engine() -> sa.engine.Engine:
    """
    Create a read-only SQLAlchemy engine for analytics queries.

    Uses ANALYTICS_DB_URL if set, otherwise falls back to DATABASE_URL
    with read-only transaction mode.
    """
    global _engine

    db_url = settings.ANALYTICS_DB_URL or settings.DATABASE_URL
    if not db_url:
        raise RuntimeError("No DATABASE_URL configured for analytics engine")

    # Strip async driver if present
    db_url = db_url.replace("+asyncpg", "")
    # Fix SSL param for psycopg2 (asyncpg uses ?ssl=require, psycopg2 uses ?sslmode=require)
    db_url = db_url.replace("?ssl=require", "?sslmode=require")
    db_url = db_url.replace("&ssl=require", "&sslmode=require")

    timeout_ms = settings.ANALYTICS_QUERY_TIMEOUT * 1000

    _engine = sa.create_engine(
        db_url,
        pool_size=3,
        max_overflow=2,
        pool_recycle=300,
        connect_args={
            "options": f"-c statement_timeout={timeout_ms} -c default_transaction_read_only=on",
        },
    )

    logger.info(
        "Analytics engine initialized (timeout=%ds, read_only=on)",
        settings.ANALYTICS_QUERY_TIMEOUT,
    )
    return _engine


async def generate_sql(query: str, llm_client) -> str:
    """
    Generate a SQL query from a natural language question.

    Args:
        query: User's natural language question.
        llm_client: LLM client with chat_completion() method.

    Returns:
        Validated SQL string.

    Raises:
        ValueError: If SQL fails validation.
    """
    schema_prompt = build_schema_prompt(query)
    system = _SQL_SYSTEM_PROMPT.format(schema=schema_prompt)

    response = await llm_client.chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ],
        temperature=0.0,
    )

    sql = _clean_sql(response)

    # Validate
    is_safe, error = validate_sql(sql)
    if not is_safe:
        raise ValueError(f"SQL validation failed: {error}")

    is_safe, error = check_cost_guard(sql)
    if not is_safe:
        raise ValueError(f"Cost guard: {error}")

    return sql


def _execute_sql_sync(sql: str) -> dict:
    """
    Execute SQL on the analytics engine (sync, runs in thread).

    Returns:
        dict with keys: columns, rows, row_count, time_ms
    """
    if _engine is None:
        raise RuntimeError("Analytics engine not initialized")

    start = time.perf_counter()

    with _engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        raw_rows = [dict(zip(columns, row)) for row in result.fetchall()]

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # Sanitize results
    rows, was_truncated = sanitize_result(raw_rows, settings.ANALYTICS_MAX_ROWS)

    # Convert non-serializable types
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
            elif isinstance(v, (float, int, str, bool, type(None))):
                pass
            else:
                row[k] = str(v)

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(raw_rows),
        "time_ms": elapsed_ms,
        "truncated": was_truncated,
    }


async def execute_sql(sql: str) -> dict:
    """Execute SQL asynchronously (wraps sync execution in thread)."""
    return await asyncio.to_thread(_execute_sql_sync, sql)


async def run_data_query(query: str, llm_client) -> dict:
    """
    Full data query pipeline: generate SQL → validate → execute → format.

    Returns:
        dict with keys: sql, columns, rows, row_count, time_ms, error, truncated
    """
    result = {
        "sql": "",
        "columns": [],
        "rows": [],
        "row_count": 0,
        "time_ms": 0,
        "error": "",
        "truncated": False,
    }

    try:
        # Step 1: Generate SQL
        sql = await generate_sql(query, llm_client)
        result["sql"] = sql

        # Step 2: Execute
        exec_result = await execute_sql(sql)
        result.update(exec_result)

    except ValueError as e:
        result["error"] = str(e)
        logger.warning("Data query validation error: %s", e)
    except sa.exc.OperationalError as e:
        error_msg = str(e)
        if "statement timeout" in error_msg.lower():
            result["error"] = f"Query timed out after {settings.ANALYTICS_QUERY_TIMEOUT}s. Try a more specific query."
        else:
            result["error"] = f"Database error: {error_msg.split(chr(10))[0]}"
        logger.error("Data query execution error: %s", e)
    except Exception as e:
        result["error"] = f"Unexpected error: {str(e)}"
        logger.error("Data query unexpected error: %s", e, exc_info=True)

    return result


# ── Helpers ───────────────────────────────────────────────────────────

def _clean_sql(response: str) -> str:
    """Extract clean SQL from LLM response, stripping markdown fences."""
    sql = response.strip()
    # Remove markdown code fences
    sql = re.sub(r'^```(?:sql)?\s*', '', sql, flags=re.MULTILINE)
    sql = re.sub(r'```\s*$', '', sql, flags=re.MULTILINE)
    sql = sql.strip()
    # Remove trailing semicolons
    sql = sql.rstrip(";")
    return sql
