"""The Ray Serve manifests must use field names Ray 2.60 reads.

Found by validating ``serveConfigV2`` against Ray 2.60.0's own schema: it accepts unknown autoscaling keys without
complaint, so ``target_num_ongoing_requests_per_replica`` (removed in favour of ``target_ongoing_requests``) was
silently ignored and Serve used its default target of 2 ongoing requests, not the 50 and 20 the manifests meant.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

DEPLOY_RAY = Path(__file__).resolve().parents[4] / "deploy" / "ray"
SERVICES = ["ray-serve-embed.yaml", "ray-serve-llm.yaml"]


def _deployments(manifest: str) -> list[dict]:
    spec = yaml.safe_load((DEPLOY_RAY / manifest).read_text())["spec"]
    config = yaml.safe_load(spec["serveConfigV2"])
    return [d for app in config["applications"] for d in app.get("deployments", [])]


@pytest.mark.parametrize("manifest", SERVICES)
def test_autoscaling_uses_the_field_ray_reads(manifest: str) -> None:
    deployments = _deployments(manifest)
    assert deployments
    for deployment in deployments:
        autoscaling = deployment["autoscaling_config"]
        assert "target_num_ongoing_requests_per_replica" not in autoscaling
        assert autoscaling["target_ongoing_requests"] > 2  # the intended value, not Ray's default


@pytest.mark.parametrize("manifest", SERVICES)
def test_the_head_names_its_dashboard_port_so_the_operator_can_find_it(manifest: str) -> None:
    """Found by running the manifest under KubeRay 1.7.2 on a local cluster: with unnamed head ports the operator
    fails with ``dashboard port is not found`` and the RayService never leaves Initializing."""
    spec = yaml.safe_load((DEPLOY_RAY / manifest).read_text())["spec"]
    head = spec["rayClusterConfig"]["headGroupSpec"]["template"]["spec"]["containers"][0]
    ports = {port.get("name"): port["containerPort"] for port in head["ports"]}
    assert ports.get("dashboard") == 8265 and ports.get("gcs-server") == 6379 and ports.get("serve") == 8000
