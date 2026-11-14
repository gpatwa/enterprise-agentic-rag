"""``scripts/set_github_secrets_azure.sh`` run against fake ``az``, ``gh`` and ``terraform`` commands.

Checks what it would do to a repository without touching one: it plans by default, sets exactly the secrets
``deploy-prod.yml`` reads, scopes them to the ``production`` environment, passes every value on stdin (never on a command
line), and creates the deploy identity with a credential for that environment and no broader roles.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "set_github_secrets_azure.sh"

FAKE = r"""#!/usr/bin/env bash
# Logs the command line, and stdin for `gh secret set`, then answers like the real tool.
name="$(basename "$0")"
echo "$name $*" >> "$FAKE_LOG"
case "$name $*" in
  "gh auth status"*|"az account show") [ "$*" = "account show" ] && { echo "{}"; exit 0; }; exit 0 ;;
  "gh repo view"*) echo "gpatwa/agentic-resolution-intelligence" ;;
  "gh api repos/gpatwa/agentic-resolution-intelligence --jq"*) echo "72292 1153827673" ;;
  "gh api"*) exit 0 ;;
  "gh secret set"*) echo "secret ${3} = $(cat)" >> "$FAKE_LOG" ;;
  "az account show --query tenantId"*) echo "tenant-0000" ;;
  "az account show --query id"*) echo "subscription-0000" ;;
  "az acr show"*) echo "/acr/id" ;;
  "az aks show"*) echo "/aks/id" ;;
  "az ad app list"*) exit 0 ;;
  "az ad app create"*) echo "client-0000" ;;
  "az ad app federated-credential list"*) exit 0 ;;
  "az role assignment list"*) exit 0 ;;
  "az role definition list"*) [ -n "${FAKE_NO_SCHEDULER_ROLE:-}" ] || echo "rag-platform-aks-scheduler" ;;
  "az group show"*) echo "/subscriptions/s/resourceGroups/rag-platform-rg" ;;
  "terraform"*)
    case "$*" in
      *"output -raw acr_name"*) echo ragplatformacr ;;
      *"output -raw aks_cluster_name"*) echo rag-platform-aks ;;
      *"output -raw resource_group_name"*) echo rag-platform-rg ;;
      *"output -raw api_identity_client_id"*) echo api-identity-0000 ;;
    esac ;;
esac
exit 0
"""


def _run(tmp_path: Path, apply: bool) -> tuple[subprocess.CompletedProcess, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("az", "gh", "terraform"):
        path = bin_dir / tool
        path.write_text(FAKE)
        path.chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    (tmp_path / "tf").mkdir(exist_ok=True)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_LOG": str(log)}
    if apply:
        env["APPLY"] = "1"
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, cwd=REPO, timeout=60)
    return result, log.read_text()


def _workflow_secrets() -> set[str]:
    job = yaml.safe_load((REPO / ".github" / "workflows" / "deploy-prod.yml").read_text())["jobs"]["deploy-azure"]
    return set(re.findall(r"secrets\.([A-Z0-9_]+)", yaml.safe_dump(job)))


def test_it_plans_by_default_and_writes_nothing(tmp_path: Path) -> None:
    result, log = _run(tmp_path, apply=False)
    assert result.returncode == 0, result.stderr
    assert "plan only" in result.stdout
    assert "secret set" not in log and "ad app create" not in log and "role assignment create" not in log


def test_apply_sets_exactly_the_secrets_the_azure_prod_job_reads(tmp_path: Path) -> None:
    result, log = _run(tmp_path, apply=True)
    assert result.returncode == 0, result.stderr
    set_names = set(re.findall(r"^secret (\S+) = ", log, flags=re.M))
    assert set_names == _workflow_secrets()
    assert "secret AZURE_CLIENT_ID = client-0000" in log and "secret ACR_NAME = ragplatformacr" in log


def test_every_secret_is_scoped_to_the_production_environment_and_passed_on_stdin(tmp_path: Path) -> None:
    _, log = _run(tmp_path, apply=True)
    for line in re.findall(r"^gh secret set .*$", log, flags=re.M):
        assert "--env production" in line and "--repo gpatwa/agentic-resolution-intelligence" in line
        assert "--body" not in line and "-b " not in line, f"a value must not be on the command line: {line}"


def test_the_identity_gets_an_environment_credential_and_three_narrow_roles(tmp_path: Path) -> None:
    _, log = _run(tmp_path, apply=True)
    assert "repo:gpatwa@72292/agentic-resolution-intelligence@1153827673:environment:production" in log
    assert "repo:gpatwa/agentic-resolution-intelligence:environment:production" not in log
    roles = re.findall(r"^az role assignment create .*--role (.+?) --scope", log, flags=re.M)
    assert sorted(roles) == sorted(["AcrPush", "Azure Kubernetes Service Cluster User Role", "rag-platform-aks-scheduler"])
    assignments = " ".join(re.findall(r"^az role assignment .*$", log, flags=re.M))
    assert not re.search(r"--role (Owner|Contributor)\b", assignments)


def test_it_does_not_create_or_change_the_environment(tmp_path: Path) -> None:
    _, log = _run(tmp_path, apply=True)
    assert not re.search(r"gh api .*(-X|--method) (PUT|POST|PATCH|DELETE)", log)


def test_it_refuses_when_terraform_has_no_outputs(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("az", "gh", "terraform"):
        path = bin_dir / tool
        path.write_text(FAKE.replace("echo ragplatformacr", "true"))
        path.chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_LOG": str(log), "APPLY": "1"}
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, cwd=REPO, timeout=60)
    assert result.returncode != 0 and "acr_name" in result.stderr
    assert "secret set" not in log.read_text()


def test_the_scheduler_role_is_assigned_only_once_terraform_has_created_it(tmp_path: Path) -> None:
    import os as _os

    _os.environ["FAKE_NO_SCHEDULER_ROLE"] = "1"
    try:
        result, log = _run(tmp_path, apply=True)
    finally:
        del _os.environ["FAKE_NO_SCHEDULER_ROLE"]
    assert result.returncode == 0, result.stderr
    assert "rag-platform-aks-scheduler' does not exist yet" in result.stdout
    assert "rag-platform-aks-scheduler --scope" not in log
