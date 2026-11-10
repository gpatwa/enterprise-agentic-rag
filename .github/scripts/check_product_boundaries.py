"""Fail when one product depends on another product's code.

Three products live in this repository and are meant to be separable (see
docs/REPO_SEPARATION_EXTRACTION_PLAN.md). Nothing is shared: this checks import-like lines in Python and
TypeScript and the COPY/ADD lines of Dockerfiles, so a dependency cannot slip in unnoticed.

Run from the repository root: python .github/scripts/check_product_boundaries.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# area -> product. A path belongs to the first matching prefix.
AREAS = {
    "services/analytics-api": "analytics",
    "apps/analytics-web": "analytics",
    "packages": "analytics",
    "services/discovery-api": "discovery",
    "apps/discovery-web": "discovery",
    "services/api": "support",
    "apps/support-web": "support",
    "pipelines": "support",
    "libs": "support",
    "models": "support",
    "eval": "support",
}

# Patterns that identify another product's code inside an import or COPY line. Module names must start a dotted path
# or follow whitespace/quote/slash, so "app.retrieval.x" does not match "eval".
_START = r"(?<![\w.])"
TOKENS = {
    "analytics": tuple(
        re.compile(p) for p in (r"analytics-api", r"analytics_api", r"analytics-web", r"platform_contracts")
    ),
    "discovery": tuple(re.compile(p) for p in (r"discovery-api", r"discovery_api", r"discovery-web")),
    "support": tuple(
        re.compile(p)
        for p in (
            r"services/api\b",
            r"services\.api\b",
            r"support-web",
            _START + r"(?:pipelines|libs|models|eval)(?:[./\s]|$)",
        )
    ),
}

PY_IMPORT = re.compile(r"^\s*(?:from\s+\S+\s+import|import\s+)\S*")
TS_IMPORT = re.compile(r"""^\s*(?:import\b.*\bfrom\b|import\s*\(|export\b.*\bfrom\b|const\b.*\brequire\()""")
DOCKER_COPY = re.compile(r"^\s*(?:COPY|ADD)\b", re.IGNORECASE)


def product_of(path: str) -> str | None:
    for prefix, product in AREAS.items():
        if path == prefix or path.startswith(prefix + "/"):
            return product
    return None


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def violations(root: Path, files: list[str]) -> list[str]:
    found: list[str] = []
    for rel in files:
        product = product_of(rel)
        if product is None:
            continue
        name = Path(rel).name
        suffix = Path(rel).suffix
        if suffix == ".py":
            is_line = PY_IMPORT.match
        elif suffix in {".ts", ".tsx", ".js", ".mjs"}:
            is_line = TS_IMPORT.match
        elif name.startswith("Dockerfile"):
            is_line = DOCKER_COPY.match
        else:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if not is_line(line):
                continue
            for other, tokens in TOKENS.items():
                if other == product:
                    continue
                match = next((m for m in (token.search(line) for token in tokens) if m), None)
                if match:
                    found.append(
                        f"{rel}:{number}: {product} code refers to {other} ({match.group(0).strip()}): {line.strip()}"
                    )
    return found


def main() -> int:
    root = Path.cwd()
    problems = violations(root, tracked_files(root))
    if problems:
        print("Product boundary violations (see docs/REPO_SEPARATION_EXTRACTION_PLAN.md):")
        print("\n".join(problems))
        return 1
    print("Product boundaries hold: no product imports another.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
