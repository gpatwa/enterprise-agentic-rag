"""Azure OpenAI without an API key: the clients, the ingestion embedder, and the files that must agree.

The API and the Ray workers authenticate to Azure OpenAI with Entra ID tokens (workload identity, or ``az login`` on a
laptop). Nothing here may need a key, every embedder must produce 768 dimensions, and the endpoint named in Helm, the Ray
job and Terraform must be the same one.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
TF = REPO / "infra" / "terraform" / "azure"
ENDPOINT = "https://rag-platform-aks-openai.openai.azure.com/"


def _run(coro):
    return asyncio.run(coro)


class _Embeddings:
    def __init__(self, dims: int) -> None:
        self.dims, self.calls = dims, []

    async def create(self, *, model, input, dimensions):
        self.calls.append({"model": model, "input": input, "dimensions": dimensions})
        items = input if isinstance(input, list) else [input]
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * self.dims) for _ in items])


class _SyncEmbeddings(_Embeddings):
    def create(self, *, model, input, dimensions):  # type: ignore[override]
        self.calls.append({"model": model, "input": input, "dimensions": dimensions})
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * self.dims) for _ in input])


# ----- the API clients -------------------------------------------------------------------------------------------------


def test_the_embed_client_asks_for_768_dimensions_from_the_deployment() -> None:
    from app.clients.azure_openai import AzureOpenAIEmbedClient

    client = AzureOpenAIEmbedClient()
    client.client = SimpleNamespace(embeddings=_Embeddings(768))
    vector = _run(client.embed_query("reset password"))
    docs = _run(client.embed_documents(["a", "b"]))
    assert len(vector) == 768 and [len(v) for v in docs] == [768, 768]
    call = client.client.embeddings.calls[0]
    assert call["model"] == "text-embedding-3-small" and call["dimensions"] == 768


def test_the_embed_client_never_returns_a_vector_of_another_size() -> None:
    from app.clients.azure_openai import AzureOpenAIEmbedClient

    client = AzureOpenAIEmbedClient()
    client.client = SimpleNamespace(embeddings=_Embeddings(1536))
    with pytest.raises(ValueError, match="1536.*768"):
        _run(client.embed_query("x"))


def test_the_llm_client_uses_the_deployment_and_json_mode() -> None:
    from app.clients.azure_openai import AzureOpenAILLMClient

    seen = {}

    class _Completions:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))])

    client = AzureOpenAILLMClient()
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    assert _run(client.chat_completion([{"role": "user", "content": "hi"}], json_mode=True)) == "hello"
    assert seen["model"] == "gpt-6-luna" and seen["response_format"] == {"type": "json_object"}
    assert seen["max_completion_tokens"] == 1024 and "max_tokens" not in seen


def test_starting_without_an_endpoint_says_what_is_missing(monkeypatch) -> None:
    from app.clients.azure_openai import AzureOpenAIEmbedClient
    from app.config import settings

    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", None)
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        _run(AzureOpenAIEmbedClient().start())


def test_starting_builds_a_token_authenticated_client_with_no_api_key(monkeypatch) -> None:
    pytest.importorskip("azure.identity.aio")  # installed from requirements.txt in CI and in the image
    from app.clients.azure_openai import AzureOpenAIEmbedClient
    from app.config import settings

    class _Credential:
        async def get_token(self, *scopes, **kwargs):
            return SimpleNamespace(token="entra-token", expires_on=9999999999)

        async def close(self):
            pass

    monkeypatch.setattr("azure.identity.aio.DefaultAzureCredential", _Credential)
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", ENDPOINT)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    client = AzureOpenAIEmbedClient()
    _run(client.start())
    assert client.client is not None and client.client._azure_ad_token_provider is not None
    _run(client.close())
    assert client.client is None


def test_the_keyless_clients_never_read_an_api_key() -> None:
    source = (REPO / "services" / "api" / "app" / "clients" / "azure_openai.py").read_text()
    code = re.sub(r'"""[\s\S]*?"""', "", source)
    assert "API_KEY" not in code and "api_key" not in code


def test_the_factory_builds_the_keyless_clients_and_lists_them_in_its_errors() -> None:
    from app.clients.azure_openai import AzureOpenAIEmbedClient, AzureOpenAILLMClient
    from app.clients.factory import create_embed_client, create_llm_client

    assert isinstance(create_llm_client("azure_openai"), AzureOpenAILLMClient)
    assert isinstance(create_embed_client(" Azure_OpenAI "), AzureOpenAIEmbedClient)
    with pytest.raises(ValueError, match="azure_openai"):
        create_llm_client("nope")
    with pytest.raises(ValueError, match="azure_openai"):
        create_embed_client("nope")


def test_local_defaults_stay_offline_and_need_no_cloud_login() -> None:
    from app.config import Settings

    fields = Settings.model_fields
    assert fields["LLM_PROVIDER"].default == "ray" and fields["EMBED_PROVIDER"].default == "ray"
    assert fields["AZURE_OPENAI_EMBED_DIMENSIONS"].default == 768
    assert fields["AZURE_OPENAI_ENDPOINT"].default is None


# ----- the ingestion embedder -------------------------------------------------------------------------------------------


def _ingest_embedder(monkeypatch, dims: int = 768):
    from pipelines.ingestion.embedding.compute import AzureOpenAIBatchEmbedder

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", ENDPOINT)
    embedder = AzureOpenAIBatchEmbedder()
    embeddings = _SyncEmbeddings(dims)
    embedder.client = SimpleNamespace(embeddings=embeddings)
    return embedder, embeddings


def test_the_ingestion_embedder_returns_768_vectors_in_batches_of_100(monkeypatch) -> None:
    embedder, embeddings = _ingest_embedder(monkeypatch)
    batch = embedder({"text": [f"chunk {i}" for i in range(230)], "metadata": [{}] * 230})
    assert len(batch["vector"]) == 230 and {len(v) for v in batch["vector"]} == {768}
    assert [len(c["input"]) for c in embeddings.calls] == [100, 100, 30]
    assert {c["dimensions"] for c in embeddings.calls} == {768}


def test_the_ingestion_embedder_fails_loudly_on_a_wrong_vector(monkeypatch) -> None:
    embedder, _ = _ingest_embedder(monkeypatch, dims=1536)
    with pytest.raises(ValueError, match="1536.*768"):
        embedder({"text": ["x"], "metadata": [{}]})


def test_the_ingestion_embedder_needs_an_endpoint_not_a_key(monkeypatch) -> None:
    from pipelines.ingestion.embedding.compute import AzureOpenAIBatchEmbedder

    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        AzureOpenAIBatchEmbedder()({"text": ["x"], "metadata": [{}]})


def test_the_ingestion_provider_selector_knows_azure_openai() -> None:
    from pipelines.ingestion.embedding.compute import AzureOpenAIBatchEmbedder, select_text_embedder

    assert select_text_embedder({"INGEST_EMBED_PROVIDER": "azure_openai"}) is AzureOpenAIBatchEmbedder


# ----- the files that must name the same account --------------------------------------------------------------------------


def _account_name() -> str:
    cluster = re.search(r'cluster_name\s*=\s*"([^"]+)"', (TF / "envs" / "prod.tfvars").read_text()).group(1)
    default = re.search(
        r'variable "openai_account_name"[\s\S]*?default\s*=\s*"([^"]*)"', (TF / "variables.tf").read_text()
    ).group(1)
    assert default == "", "the endpoint below assumes the default <cluster_name>-openai name"
    return f"{cluster}-openai"


def test_helm_ray_and_terraform_name_the_same_endpoint() -> None:
    expected = f"https://{_account_name()}.openai.azure.com/"
    assert expected == ENDPOINT
    for name in ("values-azure.yaml", "values-prod.yaml"):
        env = yaml.safe_load((REPO / "deploy" / "helm" / "api" / name).read_text())["env"]
        assert env["AZURE_OPENAI_ENDPOINT"] == expected, name
    job = yaml.safe_load((REPO / "pipelines" / "jobs" / "ray_job.yaml").read_text())["runtime_env"]["env_vars"]
    assert job["AZURE_OPENAI_ENDPOINT"] == expected


def test_the_deployment_names_in_helm_match_what_terraform_creates() -> None:
    variables = (TF / "variables.tf").read_text()

    def default(name: str) -> str:
        return re.search(rf'variable "{name}"[\s\S]*?default\s*=\s*"([^"]+)"', variables).group(1)

    for name in ("values-azure.yaml", "values-prod.yaml"):
        env = yaml.safe_load((REPO / "deploy" / "helm" / "api" / name).read_text())["env"]
        assert env["AZURE_OPENAI_LLM_DEPLOYMENT"] == default("openai_llm_deployment")
        assert env["AZURE_OPENAI_EMBED_DEPLOYMENT"] == default("openai_embed_deployment")


def test_terraform_turns_key_authentication_off_and_grants_the_identities_a_role() -> None:
    text = re.sub(r"(?m)^\s*#.*$", "", (TF / "openai.tf").read_text())
    assert re.search(r"local_auth_enabled\s*=\s*false", text), "the account must not accept keys"
    assert re.search(r"custom_subdomain_name\s*=", text), "Entra token auth needs a custom subdomain"
    assert 'kind                = "OpenAI"' in text
    roles = re.findall(r'role_definition_name\s*=\s*"([^"]+)"', text)
    assert roles and set(roles) == {"Cognitive Services OpenAI User"}
    for identity in ("api_identity", "ray_identity"):
        assert f"azurerm_user_assigned_identity.{identity}.principal_id" in text
    assert "azure_openai_endpoint" in (TF / "outputs.tf").read_text()


def test_the_ray_pods_run_as_the_service_account_with_a_workload_identity() -> None:
    spec = yaml.safe_load((REPO / "deploy" / "ray" / "ray-cluster.yaml").read_text())["spec"]
    templates = [spec["headGroupSpec"]["template"]] + [g["template"] for g in spec["workerGroupSpecs"]]
    for template in templates:
        assert template["spec"]["serviceAccountName"] == "ray-worker"
        assert template["metadata"]["labels"]["azure.workload.identity/use"] == "true"
    # the Terraform federated credential trusts exactly this service account
    assert 'subject             = "system:serviceaccount:default:ray-worker"' in (TF / "iam.tf").read_text()


def test_the_bootstraps_create_the_service_account_before_ray_needs_it() -> None:
    azure = (REPO / "scripts" / "bootstrap_cluster_azure.sh").read_text()
    assert "create serviceaccount ray-worker" in azure
    assert 'azure.workload.identity/client-id="$RAY_IDENTITY_CLIENT_ID"' in azure
    aws = (REPO / "scripts" / "bootstrap_cluster.sh").read_text()
    assert aws.index("create serviceaccount ray-worker") < aws.index("kubectl apply -f deploy/ray/ray-cluster.yaml")


def test_the_azure_bootstrap_no_longer_copies_provider_keys_into_the_app_secret() -> None:
    text = (REPO / "scripts" / "bootstrap_cluster_azure.sh").read_text()
    code = re.sub(r"(?m)^\s*#.*$", "", text)
    args = code[code.index("SECRET_ARGS=(") : code.index("kubectl create secret generic app-env-secret")]
    assert "GOOGLE_API_KEY" not in args and "TAVILY_API_KEY" not in args and "OPENAI_API_KEY" not in args


def test_the_llm_client_retries_without_temperature_when_the_model_only_takes_the_default() -> None:
    import httpx
    from openai import BadRequestError

    from app.clients.azure_openai import AzureOpenAILLMClient

    calls = []

    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            if "temperature" in kwargs:
                request = httpx.Request("POST", "https://x")
                response = httpx.Response(400, request=request)
                raise BadRequestError(
                    "Unsupported value: 'temperature' does not support 0.7 with this model.", response=response, body=None
                )
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    client = AzureOpenAILLMClient()
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    assert _run(client.chat_completion([{"role": "user", "content": "hi"}])) == "ok"
    assert _run(client.chat_completion([{"role": "user", "content": "again"}])) == "ok"
    assert ["temperature" in c for c in calls] == [True, False, False], "the second request must not retry the rejected value"


def test_other_bad_requests_are_not_swallowed() -> None:
    import httpx
    from openai import BadRequestError

    from app.clients.azure_openai import AzureOpenAILLMClient

    class _Completions:
        async def create(self, **kwargs):
            raise BadRequestError("content filter", response=httpx.Response(400, request=httpx.Request("POST", "https://x")), body=None)

    client = AzureOpenAILLMClient()
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    with pytest.raises(BadRequestError):
        _run(client.chat_completion([{"role": "user", "content": "hi"}]))
