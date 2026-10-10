"""Evidence for the approved CPU ranker dependency.

Installing LightGBM does not enable online learned ranking, bypass the
deterministic fallback, change eligibility, or add a network-backed service.
Those behaviors require later, separately reviewed milestones.
"""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

EXPECTED_VERSION = "4.5.0"
REQUIREMENTS = Path(__file__).parents[1] / "requirements.txt"


def test_requirements_pin_only_the_approved_ranker() -> None:
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()

    assert "lightgbm==4.5.0" in lines
    assert sum(line.startswith("lightgbm==") for line in lines) == 1


def test_lightgbm_import_and_version_smoke() -> None:
    try:
        installed_version = version("lightgbm")
    except PackageNotFoundError:
        pytest.skip(
            "Evidence: lightgbm==4.5.0 is pinned but unavailable in this local environment"
        )

    assert installed_version == EXPECTED_VERSION
    module = import_module("lightgbm")
    assert module.__version__ == EXPECTED_VERSION
