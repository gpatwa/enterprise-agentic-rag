# services/api/app/analytics/formatter.py
"""
Result formatting for the Data Analytics Agent.

Converts raw SQL query results into:
- HTML tables for the chat UI
- Markdown tables for LLM context (responder prompt)
- Vega-Lite chart specs for browser rendering
"""
import re
from typing import Dict, List, Optional

# Max rows to display in chat UI table
_MAX_DISPLAY_ROWS = 20
# Max rows for LLM context (to keep prompt size manageable)
_MAX_LLM_ROWS = 50


def format_as_table_html(columns: List[str], rows: List[dict]) -> str:
    """
    Generate a styled HTML table for rendering in the chat UI.

    Caps at _MAX_DISPLAY_ROWS rows for readability.
    """
    if not columns or not rows:
        return "<p><em>No results returned.</em></p>"

    display_rows = rows[:_MAX_DISPLAY_ROWS]

    header = "".join(f"<th>{_format_header(col)}</th>" for col in columns)
    body_rows = []
    for row in display_rows:
        cells = "".join(f"<td>{_format_cell(row.get(col))}</td>" for col in columns)
        body_rows.append(f"<tr>{cells}</tr>")

    table = f"""<table class="data-table">
<thead><tr>{header}</tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>"""

    if len(rows) > _MAX_DISPLAY_ROWS:
        table += f'<div class="row-count">Showing {_MAX_DISPLAY_ROWS} of {len(rows)} rows</div>'

    return table


def format_for_llm_context(columns: List[str], rows: List[dict]) -> str:
    """
    Format results as a markdown table for inclusion in the responder's LLM prompt.

    Caps at _MAX_LLM_ROWS rows.
    """
    if not columns or not rows:
        return "No data returned from the query."

    display_rows = rows[:_MAX_LLM_ROWS]

    # Header
    header = " | ".join(columns)
    separator = " | ".join("---" for _ in columns)

    # Rows
    body = []
    for row in display_rows:
        values = " | ".join(str(row.get(col, "")) for col in columns)
        body.append(values)

    result = f"{header}\n{separator}\n" + "\n".join(body)

    if len(rows) > _MAX_LLM_ROWS:
        result += f"\n\n... ({len(rows)} total rows, showing first {_MAX_LLM_ROWS})"

    return result


def suggest_chart_spec(
    columns: List[str], rows: List[dict], query: str
) -> Optional[dict]:
    """
    Suggest a Vega-Lite chart specification based on data shape and query intent.

    Heuristics:
    - Date/time column + numeric column → line chart
    - Categorical column + numeric column → bar chart
    - Two numeric columns → scatter plot

    Returns None if no suitable chart is detected.
    """
    if not columns or not rows or len(rows) < 2:
        return None

    col_types = _classify_columns(columns, rows)

    date_cols = [c for c, t in col_types.items() if t == "temporal"]
    num_cols = [c for c, t in col_types.items() if t == "quantitative"]
    cat_cols = [c for c, t in col_types.items() if t == "nominal"]

    # Prepare data for Vega-Lite (use display subset)
    chart_rows = rows[:100]
    values = [{col: row.get(col) for col in columns} for row in chart_rows]

    # Heuristic 1: Date + Number → Line chart
    if date_cols and num_cols:
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "width": 500,
            "height": 300,
            "data": {"values": values},
            "mark": {"type": "line", "point": True},
            "encoding": {
                "x": {"field": date_cols[0], "type": "temporal", "title": _format_header(date_cols[0])},
                "y": {"field": num_cols[0], "type": "quantitative", "title": _format_header(num_cols[0])},
            },
        }

    # Heuristic 2: Category + Number → Bar chart
    if cat_cols and num_cols:
        # Limit categories for readability
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "width": 500,
            "height": 300,
            "data": {"values": values[:30]},
            "mark": "bar",
            "encoding": {
                "x": {"field": cat_cols[0], "type": "nominal", "title": _format_header(cat_cols[0]),
                       "sort": "-y"},
                "y": {"field": num_cols[0], "type": "quantitative", "title": _format_header(num_cols[0])},
            },
        }
        # Horizontal bar if many categories
        if len(set(row.get(cat_cols[0]) for row in chart_rows)) > 10:
            spec["encoding"]["x"], spec["encoding"]["y"] = spec["encoding"]["y"], spec["encoding"]["x"]
            spec["encoding"]["y"]["sort"] = "-x"
        return spec

    # Heuristic 3: Two numeric columns → Scatter
    if len(num_cols) >= 2:
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "width": 500,
            "height": 300,
            "data": {"values": values},
            "mark": "point",
            "encoding": {
                "x": {"field": num_cols[0], "type": "quantitative", "title": _format_header(num_cols[0])},
                "y": {"field": num_cols[1], "type": "quantitative", "title": _format_header(num_cols[1])},
            },
        }

    return None


# ── Helpers ───────────────────────────────────────────────────────────

def _format_header(col_name: str) -> str:
    """Convert column_name to Column Name."""
    return col_name.replace("_", " ").title()


def _format_cell(value) -> str:
    """Format a cell value for HTML display."""
    if value is None:
        return '<span class="null-val">—</span>'
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.2f}"
        return f"{value:.2f}"
    if isinstance(value, int) and abs(value) >= 1000:
        return f"{value:,}"
    return str(value)


def _classify_columns(columns: List[str], rows: List[dict]) -> Dict[str, str]:
    """
    Classify columns as temporal, quantitative, or nominal
    based on column names and sample values.
    """
    col_types = {}
    sample = rows[0] if rows else {}

    for col in columns:
        val = sample.get(col)
        col_lower = col.lower()

        # Check name patterns
        if any(kw in col_lower for kw in ["date", "timestamp", "month", "year", "quarter", "week"]):
            col_types[col] = "temporal"
        elif isinstance(val, (int, float)):
            col_types[col] = "quantitative"
        elif isinstance(val, str):
            # Try parsing as date
            if _looks_like_date(val):
                col_types[col] = "temporal"
            else:
                # Check if it's a numeric string
                try:
                    float(val)
                    col_types[col] = "quantitative"
                except (ValueError, TypeError):
                    col_types[col] = "nominal"
        else:
            col_types[col] = "nominal"

    return col_types


def _looks_like_date(val: str) -> bool:
    """Check if a string looks like a date/timestamp."""
    date_patterns = [
        r'^\d{4}-\d{2}',      # 2024-01
        r'^\d{4}/\d{2}',      # 2024/01
        r'^\d{2}/\d{2}/\d{4}', # 01/15/2024
    ]
    return any(re.match(p, val) for p in date_patterns)
