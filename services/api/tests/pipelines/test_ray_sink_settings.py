"""The Ray pods carry the settings the Qdrant, Neo4j and OpenSearch sinks read, and nothing broader.

The sinks read their settings in two places: the driver (the head: ``QdrantIndexer`` and ``Neo4jIndexer`` read the
environment in ``__init__``, and the opt-in sweep's ``finalize`` talks to OpenSearch) and the workers (the pickled sinks
write, and ``OpenSearchProvider`` reads the API's settings there). So the head and both worker groups get the same sink
settings. Endpoints that are the same in every cluster built by the bootstrap scripts are literals; the OpenSearch endpoint
is external and comes from an optional ConfigMap; credentials come from one dedicated secret, one key per variable, never
``app-env-secret`` and never an ``envFrom``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
CLUSTER = REPO / "deploy" / "ray" / "ray-cluster.yaml"
CREDENTIALS = "ray-sink-credentials"
CONFIG = "ray-sink-config"

LITERALS = {
    "QDRANT_HOST": "qdrant",  # Service created by `helm upgrade --install qdrant` (the chart's name is the release name)
    "QDRANT_PORT": "6333",
    "NEO4J_URI": "bolt://neo4j:7687",  # Service created by `helm upgrade --install neo4j`
    "NEO4J_USER": "neo4j",
}
CONFIG_KEYS = ["OPENSEARCH_URL", "OPENSEARCH_AUTH_MODE"]
CREDENTIAL_KEYS = ["NEO4J_PASSWORD", "OPENSEARCH_USERNAME", "OPENSEARCH_PASSWORD", "OPENSEARCH_API_KEY"]


def _pods() -> dict[str, dict]:
    spec = yaml.safe_load(CLUSTER.read_text())["spec"]
    pods = {"head": spec["headGroupSpec"]["template"]["spec"]["containers"][0]}
    for group in spec["workerGroupSpecs"]:
        pods[group["groupName"]] = group["template"]["spec"]["containers"][0]
    return pods


def _env(container: dict) -> dict[str, dict]:
    return {entry["name"]: entry for entry in container.get("env", [])}


@pytest.mark.parametrize("pod", ["head", "cpu-workers", "gpu-workers"])
def test_every_pod_gets_the_sink_endpoints_as_literals(pod: str) -> None:
    env = _env(_pods()[pod])
    for name, value in LITERALS.items():
        assert env.get(name, {}).get("value") == value, f"{pod}: {name} should be {value!r}"


@pytest.mark.parametrize("pod", ["head", "cpu-workers", "gpu-workers"])
def test_the_opensearch_endpoint_comes_from_an_optional_configmap(pod: str) -> None:
    env = _env(_pods()[pod])
    for key in CONFIG_KEYS:
        assert "value" not in env[key], f"{pod}: {key} is external and must not be hard-coded"
        ref = env[key]["valueFrom"]["configMapKeyRef"]
        assert ref["name"] == CONFIG and ref["key"] == key and ref.get("optional") is True


@pytest.mark.parametrize("pod", ["head", "cpu-workers", "gpu-workers"])
def test_credentials_come_one_key_at_a_time_from_the_dedicated_secret(pod: str) -> None:
    env = _env(_pods()[pod])
    for key in CREDENTIAL_KEYS:
        assert "value" not in env[key], f"{pod}: {key} must not be a literal"
        ref = env[key]["valueFrom"]["secretKeyRef"]
        assert ref["name"] == CREDENTIALS and ref["key"] == key
        assert ref.get("optional") is True, f"{key}: pods must still start without the secret"


def test_only_the_workers_get_the_gemini_key() -> None:
    pods = _pods()
    assert "GOOGLE_API_KEY" not in _env(pods["head"])
    assert "GOOGLE_API_KEY" in _env(pods["cpu-workers"]) and "GOOGLE_API_KEY" in _env(pods["gpu-workers"])


def test_every_setting_the_pods_carry_is_one_the_sinks_actually_read() -> None:
    from app.config import Settings

    fields = set(Settings.model_fields)
    sources = "".join(
        (REPO / "pipelines" / "ingestion" / "indexing" / name).read_text() for name in ("qdrant.py", "neo4j.py")
    )
    for name in ("QDRANT_HOST", "QDRANT_PORT", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        assert f'"{name}"' in sources, f"the indexers no longer read {name}"
    for name in ("OPENSEARCH_URL", "OPENSEARCH_AUTH_MODE", "OPENSEARCH_USERNAME", "OPENSEARCH_PASSWORD", "OPENSEARCH_API_KEY"):
        assert name in fields, f"{name} is not a field of the API settings the OpenSearch sink reads"


@pytest.mark.parametrize("script", ["scripts/bootstrap_cluster_azure.sh", "scripts/bootstrap_cluster.sh"])
def test_bootstrap_scripts_create_the_config_and_the_credentials_without_a_secret_on_a_command_line(script: str) -> None:
    text = (REPO / script).read_text()
    start = text.index(f"kubectl create secret generic {CREDENTIALS}")
    command = text[start : text.index("\n", text.index("kubectl apply", start))]
    assert "--from-env-file=/dev/stdin" in command and "--from-literal" not in command
    assert re.search(r'printf %s "\$sink_env" \|', text[max(0, start - 200) : start + 10]), "the env file must be piped in"
    assert f"kubectl create configmap {CONFIG}" in text
    for key in CREDENTIAL_KEYS:
        assert key in text[text.index("for key in") : start], f"{script} does not collect {key}"


def test_the_sink_settings_are_created_before_the_ray_cluster_is_applied() -> None:
    text = (REPO / "scripts/bootstrap_cluster.sh").read_text()
    apply_at = text.index("kubectl apply -f deploy/ray/ray-cluster.yaml")
    assert text.index(CREDENTIALS) < apply_at and text.index(CONFIG) < apply_at
