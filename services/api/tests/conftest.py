import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]

if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))


@pytest.fixture(autouse=True)
def api_test_cwd(monkeypatch):
    # Several API tests intentionally inspect source files through paths like
    # app/config.py, matching the documented `cd services/api && pytest` workflow.
    monkeypatch.chdir(API_DIR)
