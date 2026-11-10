"""The product-boundary check fails on a cross-product dependency and passes on clean code."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from check_product_boundaries import violations  # noqa: E402


def _tree(tmp_path: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return list(files)


def test_clean_products_pass(tmp_path):
    files = _tree(
        tmp_path,
        {
            "services/analytics-api/app/a.py": "from packages.platform_contracts.semantic import X\n",
            "services/discovery-api/app/d.py": "from app.contracts.discovery import Y\nfrom app.retrieval.two_tower import Z\n",
            "services/api/app/s.py": "from app.agents.graph import G\n",
        },
    )
    assert violations(tmp_path, files) == []


def test_discovery_importing_the_analytics_contracts_fails(tmp_path):
    files = _tree(
        tmp_path, {"services/discovery-api/app/d.py": "from packages.platform_contracts.discovery import Y\n"}
    )
    assert len(violations(tmp_path, files)) == 1


def test_support_importing_packages_fails(tmp_path):
    files = _tree(tmp_path, {"services/api/app/s.py": "import packages.platform_contracts\n"})
    assert len(violations(tmp_path, files)) == 1


def test_analytics_importing_support_code_fails(tmp_path):
    files = _tree(tmp_path, {"services/analytics-api/app/a.py": "from libs.retry import retry\n"})
    assert len(violations(tmp_path, files)) == 1


def test_a_dockerfile_copying_another_product_fails(tmp_path):
    files = _tree(tmp_path, {"services/discovery-api/Dockerfile": "COPY services/analytics-api /workspace/x\n"})
    assert len(violations(tmp_path, files)) == 1


def test_a_web_app_importing_another_web_app_fails(tmp_path):
    files = _tree(tmp_path, {"apps/discovery-web/src/a.ts": "import { x } from '../../analytics-web/src/y'\n"})
    assert len(violations(tmp_path, files)) == 1


def test_words_in_prose_and_unrelated_modules_do_not_trigger(tmp_path):
    files = _tree(
        tmp_path,
        {"services/discovery-api/app/d.py": "# see analytics-api for the other product\nfrom app.models import m\n"},
    )
    assert violations(tmp_path, files) == []
