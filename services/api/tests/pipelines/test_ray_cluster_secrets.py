"""Ingestion workers get the Gemini key from a dedicated secret, and nothing else.

``INGEST_EMBED_PROVIDER=gemini`` needs ``GOOGLE_API_KEY`` on the Ray workers that run the embedder. The Ray pods had no
secrets at all. ``app-env-secret`` would have exposed the database URL and the JWT secret to them, so the key lives in
its own secret, ``ray-gemini-api-key``, and is referenced by name (never an ``envFrom``, never a literal value).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
SECRET = "ray-gemini-api-key"
CLUSTER = REPO / "deploy" / "ray" / "ray-cluster.yaml"
BOOTSTRAP_SCRIPTS = ["scripts/bootstrap_cluster_azure.sh", "scripts/bootstrap_cluster.sh"]


def _cluster() -> dict:
    return yaml.safe_load(CLUSTER.read_text())["spec"]


def _walk(node):
    """Every (key, value) pair in a parsed YAML document, at any depth (comments are not part of it)."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _containers(group: dict) -> list[dict]:
    return group["template"]["spec"]["containers"]


def test_every_worker_group_reads_the_key_from_the_dedicated_secret() -> None:
    groups = _cluster()["workerGroupSpecs"]
    assert groups, "no worker groups found"
    for group in groups:
        for container in _containers(group):
            env = {e["name"]: e for e in container.get("env", [])}
            assert "GOOGLE_API_KEY" in env, f"{group['groupName']} does not get GOOGLE_API_KEY"
            entry = env["GOOGLE_API_KEY"]
            assert "value" not in entry, "the key must come from a secret, not a literal"
            ref = entry["valueFrom"]["secretKeyRef"]
            assert ref["name"] == SECRET and ref["key"] == "GOOGLE_API_KEY"
            # Optional: a cluster without the secret (no Gemini ingestion) must still start its pods.
            assert ref.get("optional") is True


def test_the_head_and_the_ray_manifests_never_receive_the_apps_secrets() -> None:
    spec = _cluster()
    head_env = {e["name"] for c in _containers(spec["headGroupSpec"]) for e in c.get("env", [])}
    assert "GOOGLE_API_KEY" not in head_env, "the head only runs the job driver; it does not embed"
    for path in sorted((REPO / "deploy" / "ray").glob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            for key, value in _walk(doc):
                assert key != "envFrom", f"{path.name} uses envFrom; reference single keys instead"
                if key == "secretKeyRef":
                    assert value["name"] != "app-env-secret", f"{path.name} exposes the app-wide secret to Ray"


@pytest.mark.parametrize("script", BOOTSTRAP_SCRIPTS)
def test_bootstrap_scripts_create_the_dedicated_secret_without_putting_the_key_on_a_command_line(script: str) -> None:
    text = (REPO / script).read_text()
    assert SECRET in text, f"{script} does not create {SECRET}"
    # Pipe the value in on stdin: a --from-literal argument is visible to every process on the machine.
    assert re.search(r'printf %s "\$GOOGLE_API_KEY" \|\s*\\?\s*kubectl create secret generic ' + SECRET, text), (
        f"{script} must create {SECRET} from stdin"
    )
    start = text.index(f"kubectl create secret generic {SECRET}")
    command = text[start : text.index("\n", text.index("kubectl apply", start))]
    assert "--from-literal" not in command and "--from-file=GOOGLE_API_KEY=/dev/stdin" in command


def test_the_ray_secret_is_created_before_the_ray_cluster_is_applied() -> None:
    text = (REPO / "scripts/bootstrap_cluster.sh").read_text()
    assert text.index(SECRET) < text.index("kubectl apply -f deploy/ray/ray-cluster.yaml")
