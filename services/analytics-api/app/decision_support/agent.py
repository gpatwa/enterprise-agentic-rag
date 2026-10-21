"""The review assistant: reads pending reviews, writes a short note for the human reviewer, and decides nothing.

It authenticates with its own app identity (an Entra app role `Analytics.ReviewAssistant`, which gives only the read-only
`analytics-review-assistant` group), calls the two read-only endpoints, and prints one JSON note per pending review. It cannot
decide: the decision endpoint needs the reviewer group and refuses automated callers. It costs no model tokens (the note is
mechanical); a model-written summary could be added later without changing what it is allowed to do.

    python -m app.decision_support.agent --api https://<api> --token "$ASSISTANT_TOKEN" [--api-key "$API_KEY"] [--purpose analytics]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any


def draft_note(brief: dict[str, Any]) -> dict[str, Any]:
    advisory = brief["advisory"]
    facts = [
        f"asks for {', '.join(brief['metrics']) or 'no metric'}"
        + (f" grouped by {', '.join(brief['group_by'])}" if brief["group_by"] else ""),
        f"on {brief['dataset']} ({brief['dialect']})",
        f"estimated cost {brief['estimated_cost_units']} of a limit of {brief['run_cost_limit']}",
        f"requested by {brief['requested_by']}, expires {brief['expires_at']}",
    ]
    attention = advisory["reasons"]
    summary = (
        "; ".join(facts)
        + ". "
        + (
            "Needs attention: " + "; ".join(attention)
            if attention
            else "The mechanical checks pass; a person still decides."
        )
    )
    return {
        "review_id": brief["review_id"],
        "run_id": brief["run_id"],
        "suggestion": advisory["suggestion"],
        "summary": summary,
        "plan_fingerprint": brief["plan_fingerprint"],
        "decision_authority": "none",
    }


def run_once(get: Callable[[str, dict[str, str]], Any], purpose: str = "analytics") -> list[dict[str, Any]]:
    """`get(path, params)` returns parsed JSON for a GET against `/api/v2/analytics`; briefs that cannot be read are skipped."""
    notes = []
    for item in get("/reviews/pending", {"purpose": purpose})["reviews"]:
        try:
            brief = get(f"/runs/{item['run_id']}/review-brief", {"purpose": purpose})
        except LookupError:
            continue  # decided or expired between the list and the read
        notes.append(draft_note(brief))
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--purpose", default="analytics")
    args = parser.parse_args(argv)
    import httpx

    headers = {"Authorization": f"Bearer {args.token}", **({"X-API-Key": args.api_key} if args.api_key else {})}

    def get(path: str, params: dict[str, str]) -> Any:
        response = httpx.get(
            f"{args.api.rstrip('/')}/api/v2/analytics{path}", params=params, headers=headers, timeout=20.0
        )
        if response.status_code in (404, 409):
            raise LookupError(path)
        response.raise_for_status()
        return response.json()

    for note in run_once(get, args.purpose):
        print(json.dumps(note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
