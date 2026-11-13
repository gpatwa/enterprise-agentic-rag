"""One live Azure environment, named ``prod``, with no staging in front of it (owner decision, 2026-11-12).

Two things used to break that. The Terraform removed the Postgres firewall rule and Redis public access whenever
``environment == "prod"`` while the private-networking replacements were still commented out, so a prod apply would have
cut AKS off from both. And ``deploy-prod.yml`` could only promote an image that ``deploy-staging.yml`` had built.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
TF = REPO / "infra" / "terraform" / "azure"


def test_network_exposure_does_not_depend_on_the_environment_name() -> None:
    for name in ("postgres.tf", "redis.tf"):
        text = re.sub(r"(?m)^\s*#.*$", "", (TF / name).read_text())
        assert 'var.environment == "prod"' not in text, f"{name} switches exposure on the environment name"
    assert "var.allow_public_data_services" in (TF / "postgres.tf").read_text()
    assert "var.allow_public_data_services" in (TF / "redis.tf").read_text()


def test_the_exposure_switch_defaults_to_public_and_prod_sets_it_explicitly() -> None:
    variables = (TF / "variables.tf").read_text()
    block = variables[variables.index('variable "allow_public_data_services"') :]
    assert re.search(r"default\s*=\s*true", block)
    assert re.search(r"(?m)^allow_public_data_services\s*=\s*true", (TF / "envs" / "prod.tfvars").read_text())


def test_the_azure_prod_job_can_build_its_own_image() -> None:
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "deploy-prod.yml").read_text())
    image_tag = workflow[True]["workflow_dispatch"]["inputs"]["image_tag"]  # PyYAML reads the key `on` as True
    assert image_tag["required"] is False and image_tag["default"] == ""
    steps = workflow["jobs"]["deploy-azure"]["steps"]
    script = next(s["run"] for s in steps if s.get("name") == "Build or retag for production")
    assert "docker build" in script and "docker push" in script and "-z" in script


def test_the_aws_prod_job_still_requires_a_tag() -> None:
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "deploy-prod.yml").read_text())
    names = [s.get("name") for s in workflow["jobs"]["deploy-aws"]["steps"]]
    assert names.index("Require an image tag") < names.index("Retag for production")


# ----- the bootstrap needs no typing and does not rotate secrets -------------------------------------------------------


def test_azure_bootstrap_never_prompts_and_never_regenerates_the_jwt_key() -> None:
    text = (REPO / "scripts" / "bootstrap_cluster_azure.sh").read_text()
    code = re.sub(r"(?m)^\s*#.*$", "", text)
    assert not re.search(r"\bread\s+-", code), "the bootstrap must not wait for typed input"
    assert "openssl rand -hex 32" not in code, "a fresh JWT key per run invalidates every issued token"
    for name, tfvar, vault in (
        ("DB_PASSWORD", "db_password", "db-password"),
        ("JWT_SECRET_KEY", "jwt_secret_key", "jwt-secret-key"),
        ("NEO4J_PASSWORD", "neo4j_password", "neo4j-password"),
    ):
        assert f"resolve_secret {name} {tfvar} {vault}" in code
    # Every Key Vault name the script reads is one Terraform writes.
    keyvault = (TF / "keyvault.tf").read_text()
    for vault in ("db-password", "jwt-secret-key", "neo4j-password", "gemini-api-key", "tavily-api-key"):
        assert f'name         = "{vault}"' in keyvault


def test_azure_bootstrap_builds_the_image_before_the_helm_install() -> None:
    text = (REPO / "scripts" / "bootstrap_cluster_azure.sh").read_text()
    build = text.index("az acr build")
    assert 'az acr repository show --name "$ACR_NAME"' in text[:build], "build only when the tag is missing"
    assert build < text.index("helm upgrade --install api")
