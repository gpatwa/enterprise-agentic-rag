"""Final-evaluation packets ADS-071..078 (M7). Fakes only; every threshold file is PROPOSED until the user approves it.

Each `run_*` returns a report dict with `ok` (all gates met) and the approval statuses of its thresholds and of the corpus it used.
`ok` means the proposed gates were met on the reference stack; it never means an owner approved anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reference_stack import golden
from reference_stack import m7_corpus as corpus_module

M7 = Path(__file__).parent / "m7"
E2E_THRESHOLDS = M7 / "e2e-thresholds.proposed.json"


def _corpus_approval() -> dict[str, Any]:
    return json.loads(corpus_module.APPROVAL.read_text())["approval"]


def run_correctness(engines=("duckdb", "postgres")) -> dict[str, Any]:
    """ADS-071: end-to-end correctness and PostgreSQL/DuckDB equivalence on the pinned corpus."""
    report = golden.run_golden(tuple(engines), corpus=corpus_module.CORPUS, thresholds_path=E2E_THRESHOLDS)
    report["corpus_approval"] = _corpus_approval()
    report["ok"] = bool(report["meets_thresholds"])
    report["packet"] = "ADS-071"
    return report


def render_correctness(report: dict[str, Any]) -> str:
    base = golden.render_markdown(report)
    base = base.replace(
        "# ADS-049: Milestone-4 Golden Report",
        "# ADS-071: End-to-End Correctness and Dialect Equivalence (M7 reference corpus)",
    )
    for old, new in (
        ("by `make analytics-golden`", "by `make analytics-m7-correctness`"),
        (
            "This is not the M4 `local_demo_review` approval and does not imply it; no packet has had independent review.",
            "This is not an approval of anything and does not imply one; no packet has had independent review.",
        ),
        (
            "Scripted model (three phrasings plus adversarial inputs)",
            "Scripted model (the ADS-070 phrasings plus adversarial inputs)",
        ),
        ("## Not measured at M4", "## Not measured here"),
        (
            "- The M4 `local_demo_review` human gate, and independent review of ADS-040 to ADS-049.",
            "- Approval of the corpus (definition and results owners), approval of the thresholds, and the final go/no-go.",
        ),
    ):
        base = base.replace(old, new)
    caveat = (
        "\n> **Approval status:** thresholds are "
        f"`{report['approval']['status']}`; the corpus approvals are `{report['corpus_approval']['status']}` "
        "(definition owner and results owner have not approved). A pass here is not a go/no-go.\n"
    )
    head, _, tail = base.partition("\n## Scope and limits")
    return head + caveat + "\n## Scope and limits" + tail


def _retrieval():
    from reference_stack import retrieval_eval

    return ("ADS-072-retrieval-report", retrieval_eval.run_retrieval, retrieval_eval.render_markdown)


PACKETS = {
    "071": ("ADS-071-correctness-report", run_correctness, render_correctness),
}
PACKETS["072"] = _retrieval()


def _abstention():
    from reference_stack import abstention_eval

    return ("ADS-073-abstention-report", abstention_eval.run_abstention, abstention_eval.render_markdown)


PACKETS["073"] = _abstention()


def _isolation():
    from reference_stack import isolation_eval

    return ("ADS-074-isolation-report", isolation_eval.run_isolation, isolation_eval.render_markdown)


PACKETS["074"] = _isolation()
