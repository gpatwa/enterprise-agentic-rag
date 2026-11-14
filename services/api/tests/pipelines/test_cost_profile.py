"""The cost-optimised profile: everything the platform requests fits on two small nodes.

The cluster is billed by node, and nodes are bought for what pods *request*, not what they use. Measured on the live
cluster: the pods used ~0.5 vCPU in total while requesting 5.3, which kept the autoscaler at three app nodes. These tests
keep the requests small enough for one system node (B2s) and one app node (B2s_v2), using the overheads measured there.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]

# Measured on the live AKS (kubectl): allocatable per node, and the kube-system add-ons' requests.
NODES = {"system B2s": (1.9, 3080), "app B2s_v2": (1.9, 7180)}  # (CPU, memory MiB) allocatable
KUBE_SYSTEM_FIXED = (0.79, 524)
KUBE_SYSTEM_PER_NODE = (0.27, 226)
# Pods whose requests come from charts we do not own (measured): KubeRay operator, ingress controller, Neo4j (the chart's
# own floor: 0.5 CPU and 2Gi).
KUBERAY = (0.10, 512)
INGRESS = (0.10, 90)
NEO4J = (0.50, 2048)


def _cpu(value) -> float:
    value = str(value)
    return float(value[:-1]) / 1000 if value.endswith("m") else float(value)


def _mem(value) -> float:
    value = str(value)
    for suffix, factor in (("Gi", 1024), ("Mi", 1), ("G", 954), ("M", 0.954)):
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * factor
    raise ValueError(value)


def _values(path: str) -> dict:
    return yaml.safe_load((REPO / path).read_text())


def _requests(resources: dict) -> tuple[float, float]:
    req = resources["requests"]
    return _cpu(req["cpu"]), _mem(req["memory"])


def _platform_requests() -> dict[str, tuple[float, float]]:
    prod = _values("deploy/helm/api/values-prod.yaml")
    base = _values("deploy/helm/api/values.yaml")
    cluster = yaml.safe_load((REPO / "deploy" / "ray" / "ray-cluster-azure.yaml").read_text())["spec"]
    head = cluster["headGroupSpec"]["template"]["spec"]["containers"][0]["resources"]
    return {
        "api x2": tuple(2 * x for x in _requests(prod["resources"])),
        "support worker": _requests(base["supportWorker"]["resources"]),
        "qdrant": _requests(_values("deploy/helm/qdrant/values-azure.yaml")["resources"]),
        "neo4j": NEO4J,
        "kuberay operator": KUBERAY,
        "ingress": INGRESS,
        "ray head": _requests(head),
    }


def _steady_state() -> dict[str, tuple[float, float]]:
    """What runs all the time: everything except the Ray head, which is suspended between ingestions."""
    return {name: req for name, req in _platform_requests().items() if name != "ray head"}


def test_the_platform_fits_on_two_small_nodes_with_headroom() -> None:
    pods = _steady_state()
    cpu = sum(c for c, _ in pods.values()) + KUBE_SYSTEM_FIXED[0] + 2 * KUBE_SYSTEM_PER_NODE[0]
    mem = sum(m for _, m in pods.values()) + KUBE_SYSTEM_FIXED[1] + 2 * KUBE_SYSTEM_PER_NODE[1]
    cap_cpu = sum(c for c, _ in NODES.values())
    cap_mem = sum(m for _, m in NODES.values())
    assert cpu <= 0.7 * cap_cpu, f"requests {cpu:.2f} CPU of {cap_cpu:.2f}: no headroom for a rolling update"
    assert mem <= 0.6 * cap_mem, f"requests {mem:.0f} MiB of {cap_mem}: not below the autoscaler's 50% scale-down line"


def test_the_ray_cluster_is_suspended_while_idle_and_the_script_resumes_and_suspends_it() -> None:
    """Found live: the idle head's 2.5Gi kept the second app node at 53% memory, above the 50% scale-down threshold."""
    cluster = yaml.safe_load((REPO / "deploy" / "ray" / "ray-cluster-azure.yaml").read_text())["spec"]
    assert cluster["suspend"] is True
    script = (REPO / "scripts" / "ingest_azure.sh").read_text()
    assert "set_suspend false" in script and "set_suspend true" in script
    assert script.index("trap cleanup EXIT") < script.index("set_suspend false"), "the trap must exist before the resume"


def test_a_run_adds_the_head_and_a_worker_and_still_fits_on_three_nodes() -> None:
    steady = _steady_state()
    head = _platform_requests()["ray head"]
    worker = (1.0, 3072)  # the worker's own request (deploy/ray/ray-cluster-azure.yaml)
    cpu = sum(c for c, _ in steady.values()) + head[0] + worker[0] + KUBE_SYSTEM_FIXED[0] + 3 * KUBE_SYSTEM_PER_NODE[0]
    mem = sum(m for _, m in steady.values()) + head[1] + worker[1] + KUBE_SYSTEM_FIXED[1] + 3 * KUBE_SYSTEM_PER_NODE[1]
    assert cpu <= 3 * 1.9 * 0.85 and mem <= (3080 + 2 * 7180) * 0.85


def test_the_requests_that_drove_the_third_node_stay_small() -> None:
    pods = _platform_requests()
    assert pods["api x2"][0] <= 0.4, "the API pods measured ~3m CPU each"
    assert pods["qdrant"][0] <= 0.25 and pods["ray head"][0] <= 0.5
    assert pods["support worker"][0] <= 0.25


def test_limits_still_allow_a_burst() -> None:
    """Small requests must not become small limits: ingestion bursts and rolling starts need the room."""
    prod = _values("deploy/helm/api/values-prod.yaml")["resources"]["limits"]
    assert _cpu(prod["cpu"]) >= 1 and _mem(prod["memory"]) >= 1024
    qdrant = _values("deploy/helm/qdrant/values-azure.yaml")["resources"]["limits"]
    assert _mem(qdrant["memory"]) >= 2048


def test_an_ingestion_run_adds_one_worker_node_not_a_permanent_one() -> None:
    """The worker (1 CPU / 3Gi) is what triggers the autoscaler; it exists only while a run scales it up."""
    cluster = yaml.safe_load((REPO / "deploy" / "ray" / "ray-cluster-azure.yaml").read_text())["spec"]
    assert cluster["workerGroupSpecs"][0]["replicas"] == 0
    assert "scale_workers 0" in (REPO / "scripts" / "ingest_azure.sh").read_text()
    assert yaml.safe_load((REPO / "deploy" / "ray" / "ray-cluster-azure.yaml").read_text())["spec"]["workerGroupSpecs"][0]["template"]["spec"]["containers"][0]["resources"]["requests"]["cpu"] == "1"


def test_the_neo4j_override_is_documented_as_the_chart_floor_not_a_missed_saving() -> None:
    text = (REPO / "deploy" / "helm" / "neo4j" / "values-azure.yaml").read_text()
    assert re.search(r"refuses anything below 0\.5 CPU and 2Gi", text)


# ----- the off-hours schedule ---------------------------------------------------------------------------------------------

WORKFLOW = REPO / ".github" / "workflows" / "azure-schedule.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _run_script() -> str:
    steps = _workflow()["jobs"]["schedule"]["steps"]
    return next(s["run"] for s in steps if s.get("name") == "Start, stop or report")


def test_the_schedule_is_up_in_working_hours_and_down_nights_and_weekends() -> None:
    crons = [s["cron"] for s in _workflow()[True]["schedule"]]
    assert sorted(crons) == ["0 14 * * 1-5", "0 2 * * 2-6"]
    # start Mon-Fri 14:00 UTC, stop 02:00 UTC the next day (Tue-Sat): 12 hours up, five days a week
    hours_up = 5 * (24 - 14 + 2)
    assert hours_up == 60 and hours_up / 168 < 0.4, "the saving assumed in the cost analysis is ~36% uptime"


def test_the_schedule_job_uses_the_production_identity_and_the_pause_switch() -> None:
    job = _workflow()["jobs"]["schedule"]
    assert job["environment"] == "production"
    assert "vars.SCHEDULE_PAUSED" in job["if"] and "github.event_name != 'schedule'" in job["if"]
    secrets = set(re.findall(r"secrets\.([A-Z0-9_]+)", yaml.safe_dump(job)))
    deploy = yaml.safe_load((REPO / ".github" / "workflows" / "deploy-prod.yml").read_text())["jobs"]["deploy-azure"]
    assert secrets <= set(re.findall(r"secrets\.([A-Z0-9_]+)", yaml.safe_dump(deploy))), "only secrets that already exist"
    assert _workflow()["concurrency"]["cancel-in-progress"] is False


def test_start_brings_the_database_up_first_and_stop_takes_it_down_last() -> None:
    script = _run_script()
    start = script[script.index("start)") : script.index("stop)")]
    stop = script[script.index("stop)") : script.index("status)")]
    assert start.index("flexible-server start") < start.index("az aks start")
    assert stop.index("az aks stop") < stop.index("flexible-server stop")


def test_the_schedule_only_starts_stops_and_reads() -> None:
    script = _run_script()
    assert not re.search(r"\b(delete|purge|update|scale|upgrade|create)\b", script)
    assert set(re.findall(r"az (?:aks|postgres flexible-server) (\w+)", script)) <= {"show", "list", "start", "stop"}


def test_the_scheduler_role_can_only_read_start_and_stop_the_cluster_and_database() -> None:
    text = re.sub(r"(?m)^\s*#.*$", "", (REPO / "infra" / "terraform" / "azure" / "scheduler.tf").read_text())
    actions = re.findall(r'"(Microsoft\.[A-Za-z/]+)"', text)
    assert actions, "no actions found"
    for action in actions:
        assert action.endswith(("/read", "/start/action", "/stop/action")), f"{action} is more than read, start or stop"
    assert not re.search(r'"\*"|/\*"', text), "no wildcard permissions"
    assert "not_actions = []" in text and "assignable_scopes = [azurerm_resource_group.main.id]" in text


def test_the_script_assigns_the_role_terraform_defines() -> None:
    script = (REPO / "scripts" / "set_github_secrets_azure.sh").read_text()
    assert 'scheduler_role="${aks_name}-scheduler"' in script
    assert 'name        = "${var.cluster_name}-scheduler"' in (REPO / "infra" / "terraform" / "azure" / "scheduler.tf").read_text()
