"""The OpenSearch sink must import with only the dependencies the ingestion image declares.

``Dockerfile.ingestion`` installs ``requirements-ingestion.txt`` and nothing else. The sink imports
``services/api/app/search`` and ``app.config``, so what those need (pydantic, pydantic-settings, opensearch-py with
its ``async`` extra) must be declared there with the API's pins, and ``services/api/app`` must be copied and on
``PYTHONPATH``. The image is not built here (its dependencies are heavy); these tests check what can be checked
without that:

* the declared requirements agree with ``services/api/requirements.txt``;
* in a subprocess where every third-party module that is not provided by the declared requirements (and their
  installed transitive dependencies) is blocked, the sink modules still import, and the same check FAILS when the
  OpenSearch lines are removed, so it can tell the difference;
* the Dockerfile, compose file and ``.dockerignore`` agree with the above.

Not covered: that pip can resolve the whole file together (ray 2.60, unstructured 0.12, pydantic 2.6), that the
image builds, and anything about packages that are declared but not installed in the environment running this test.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
API_REQUIREMENTS = REPO / "services" / "api" / "requirements.txt"
IMAGE_REQUIREMENTS = REPO / "requirements-ingestion.txt"
PIPELINE_REQUIREMENTS = REPO / "pipelines" / "ingestion" / "requirements.txt"
RAY_JOB = REPO / "pipelines" / "jobs" / "ray_job.yaml"
JOB_HANDLER = REPO / "pipelines" / "jobs" / "s3_event_handler.py"

# Distribution name -> what the OpenSearch sink needs from it, taken from services/api/requirements.txt.
SINK_PACKAGES = ("opensearch-py", "pydantic", "pydantic-settings")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _spec_by_name(lines: list[str]) -> dict[str, str]:
    specs: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^([A-Za-z0-9_.-]+)(\[[^\]]*\])?\s*(.*)$", line)
        if match:
            specs[_normalize(match.group(1))] = (match.group(2) or "") + match.group(3).strip()
    return specs


def test_sink_dependencies_are_declared_with_the_apis_pins() -> None:
    api = _spec_by_name(_requirement_lines(API_REQUIREMENTS))
    for path in (IMAGE_REQUIREMENTS, PIPELINE_REQUIREMENTS):
        declared = _spec_by_name(_requirement_lines(path))
        for package in SINK_PACKAGES:
            assert package in declared, f"{path.name} does not declare {package}"
            # The API pins the plain package; the pipeline adds the async extra to opensearch-py and nothing else.
            assert declared[package].replace("[async]", "") == api[package], (
                f"{path.name}: {package} is {declared[package]!r} but services/api pins {api[package]!r}"
            )
    assert _spec_by_name(_requirement_lines(IMAGE_REQUIREMENTS))["opensearch-py"].startswith("[async]"), (
        "opensearch-py needs the async extra (aiohttp); without it the provider cannot build its client"
    )


def test_ray_job_configs_install_the_same_sink_packages() -> None:
    api = _spec_by_name(_requirement_lines(API_REQUIREMENTS))
    job_text = RAY_JOB.read_text() + JOB_HANDLER.read_text()
    for package in SINK_PACKAGES:
        extra = "[async]" if package == "opensearch-py" else ""
        assert f"{package}{extra}{api[package]}" in job_text.replace(" ", ""), (
            f"a Ray job's pip list is missing {package}{extra}{api[package]}"
        )
    assert "opensearch-py[async]" in RAY_JOB.read_text() and "opensearch-py[async]" in JOB_HANDLER.read_text()


def test_dockerfile_compose_and_dockerignore_ship_and_find_the_api_package() -> None:
    dockerfile = (REPO / "Dockerfile.ingestion").read_text()
    assert re.search(r"^ENV PYTHONPATH=/app:/app/services/api\s*$", dockerfile, re.MULTILINE)
    assert "requirements-ingestion.txt" in dockerfile
    compose = (REPO / "docker-compose.yml").read_text()
    assert "PYTHONPATH=/app:/app/services/api" in compose
    ignore = (REPO / ".dockerignore").read_text().splitlines()
    assert "!services/api/app/" in ignore and "!services/api/app/**" in ignore
    # Only the package: tests, migrations and the API's own Dockerfile stay out of the ingestion image.
    assert "!services/api/" not in ignore and "!services/api/**" not in ignore


# ----- a subprocess that blocks every module the declared requirements do not provide --------------------------------

CHECK_SCRIPT = r"""
import importlib.metadata as md
import json
import sys

from packaging.markers import default_environment
from packaging.requirements import Requirement

config = json.loads(sys.argv[1])
declared = [Requirement(line) for line in config["requirements"]]

installed = {}
for dist in md.distributions():
    installed[dist.metadata["Name"].lower().replace("_", "-").replace(".", "-")] = dist


def key(name):
    return name.lower().replace("_", "-").replace(".", "-")


closure = set()
pending = [(requirement.name, set(requirement.extras)) for requirement in declared]
while pending:
    name, extras = pending.pop()
    dist = installed.get(key(name))
    if dist is None or (key(name), frozenset(extras)) in closure:
        continue
    closure.add((key(name), frozenset(extras)))
    for text in dist.requires or []:
        requirement = Requirement(text)
        if requirement.marker is not None and not any(
            requirement.marker.evaluate({**default_environment(), "extra": extra}) for extra in (extras or {""})
        ):
            continue
        pending.append((requirement.name, set(requirement.extras)))
allowed_dists = {name for name, _ in closure}

allowed = set(sys.stdlib_module_names) | {"pipelines", "app"} | {"packaging", "importlib_metadata"}
for module, dists in md.packages_distributions().items():
    if any(key(d) in allowed_dists for d in dists):
        allowed.add(module)


class Blocker:
    def find_spec(self, name, path=None, target=None):
        top = name.split(".")[0]
        if top in allowed or top.startswith("_"):
            return None
        raise ImportError(f"{top!r} is not provided by the declared requirements")


sys.meta_path.insert(0, Blocker())
for module in config["modules"]:
    __import__(module)
print(json.dumps({"ok": True}))
"""


def _run_import_check(requirements: list[str], *, api_on_path: bool) -> subprocess.CompletedProcess[str]:
    import os

    paths = [str(REPO)] + ([str(REPO / "services" / "api")] if api_on_path else [])
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("OPENSEARCH_ENABLED", None)
    payload = {
        "requirements": requirements,
        "modules": ["pipelines.ingestion.indexing.opensearch", "pipelines.ingestion.indexing.sinks"],
    }
    return subprocess.run(
        [sys.executable, "-c", CHECK_SCRIPT, json.dumps(payload)],
        env=env,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _installed(*names: str) -> bool:
    import importlib.metadata as md

    try:
        for name in names:
            md.version(name)
    except md.PackageNotFoundError:
        return False
    return True


needs_sink_packages = pytest.mark.skipif(
    not (_installed(*SINK_PACKAGES, "aiohttp", "packaging")),
    reason="needs the packages the sink declares, and aiohttp for the async extra, installed to inspect them",
)


@needs_sink_packages
def test_sink_modules_import_with_only_the_declared_image_requirements() -> None:
    result = _run_import_check(_requirement_lines(IMAGE_REQUIREMENTS), api_on_path=True)
    assert result.returncode == 0, result.stderr[-2000:]


@needs_sink_packages
def test_the_check_fails_without_the_opensearch_lines_so_it_can_tell() -> None:
    before = [line for line in _requirement_lines(IMAGE_REQUIREMENTS) if _spec_key(line) not in SINK_PACKAGES]
    result = _run_import_check(before, api_on_path=True)
    assert result.returncode != 0
    assert "is not provided by the declared requirements" in result.stderr


def _spec_key(line: str) -> str:
    return _normalize(re.match(r"^([A-Za-z0-9_.-]+)", line).group(1))


@needs_sink_packages
def test_the_async_extra_is_what_brings_aiohttp() -> None:
    """The provider builds ``AsyncOpenSearch``, which opensearch-py only has when aiohttp is installed.

    Found on a real run: with plain ``opensearch-py`` the import succeeds and the first write fails with
    "opensearch-py is required to construct the OpenSearch provider".
    """
    from importlib.metadata import requires

    assert any("aiohttp" in r and "async" in r for r in (requires("opensearch-py") or [])), (
        "opensearch-py no longer ships an [async] extra backed by aiohttp; revisit the declared requirement"
    )


@needs_sink_packages
def test_the_sink_finds_services_api_on_its_own_when_pythonpath_lacks_it() -> None:
    """A Ray job shipping the repository with ``working_dir`` has the repo root on the path and nothing more."""
    result = _run_import_check(_requirement_lines(IMAGE_REQUIREMENTS), api_on_path=False)
    assert result.returncode == 0, result.stderr[-2000:]
