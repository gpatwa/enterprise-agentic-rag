"""The API must be pointed at the Services the Helm releases actually create.

The bootstrap scripts install Qdrant and Neo4j as releases named ``qdrant`` and ``neo4j``; ``helm template`` of both charts
with the repo's values renders the Services ``qdrant`` (6333) and ``neo4j`` (bolt 7687). The API's code defaults are
``qdrant-service`` and ``bolt://neo4j-cluster:7687``, which match no rendered Service, and only ``values-staging.yaml``
overrode them, so the Azure and prod API values pointed at hosts that do not resolve.

``QDRANT_PORT`` is set with the host on purpose: Kubernetes injects ``QDRANT_PORT=tcp://<ip>:6333`` into pods that share a
namespace with a Service named ``qdrant``, and the API parses that variable as an integer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
EXPECTED = {"QDRANT_HOST": "qdrant", "QDRANT_PORT": "6333", "NEO4J_URI": "bolt://neo4j:7687"}


def _env(name: str) -> dict:
    return yaml.safe_load((REPO / "deploy" / "helm" / "api" / name).read_text())["env"]


@pytest.mark.parametrize("values_file", ["values-azure.yaml", "values-prod.yaml", "values-staging.yaml"])
def test_the_api_values_point_at_the_services_the_charts_create(values_file: str) -> None:
    env = _env(values_file)
    for key, value in EXPECTED.items():
        assert env.get(key) == value, f"{values_file}: {key} is {env.get(key)!r}, expected {value!r}"


@pytest.mark.parametrize("values_file", ["values-azure.yaml", "values-prod.yaml"])
def test_the_port_is_an_integer_so_a_kubernetes_injected_value_cannot_replace_it(values_file: str) -> None:
    assert int(_env(values_file)["QDRANT_PORT"]) == 6333


def test_the_api_and_the_ray_pods_agree_on_the_hosts() -> None:
    cluster = yaml.safe_load((REPO / "deploy" / "ray" / "ray-cluster.yaml").read_text())["spec"]
    container = cluster["headGroupSpec"]["template"]["spec"]["containers"][0]
    ray_env = {e["name"]: e.get("value") for e in container["env"]}
    api_env = _env("values-azure.yaml")
    for key in EXPECTED:
        assert ray_env[key] == api_env[key], f"{key}: Ray pods use {ray_env[key]!r}, the API uses {api_env[key]!r}"
