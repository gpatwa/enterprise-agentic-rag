"""Makes ``services/api`` importable for the OpenSearch sink, which reuses the support API's ``app.*`` modules.

The image and docker-compose set ``PYTHONPATH`` for this. Ray jobs that ship the repository with
``runtime_env.working_dir`` do not (the working directory is the repository root, not ``services/api``), so the
sink adds the directory itself. It is appended, never inserted, so it cannot shadow anything already importable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[3] / "services" / "api"


def ensure_api_importable() -> None:
    if importlib.util.find_spec("app") is None and (API_DIR / "app").is_dir():
        sys.path.append(str(API_DIR))
    if importlib.util.find_spec("app") is None:
        raise ImportError(
            "the OpenSearch sink needs services/api/app on the Python path (it shares the support API's document "
            f"schema); expected it under {API_DIR}. Ship it with the pipeline (see .dockerignore) or set PYTHONPATH."
        )
