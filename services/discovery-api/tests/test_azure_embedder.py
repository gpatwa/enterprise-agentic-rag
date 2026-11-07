"""Azure OpenAI embedder, its config validation, bootstrap guard and service fallback. No network, no spend."""

from __future__ import annotations

import json
import math

import httpx
import pytest

from app.config import DiscoverySettings, Environment, settings_from_env
from app.embedding import HashingEmbedder, create_embedder
from app.embedding.azure_openai import AzureOpenAIEmbedder, EmbeddingBudgetExceeded, EmbeddingError
from app.opensearch import bootstrap
from app.opensearch.client import OpenSearchUnavailable
from app.opensearch.service import OpenSearchSearchService

ENDPOINT = "https://example.openai.azure.com"
KEY = "test-key-123"
DIMS = 16


def _vector(seed: float) -> list[float]:
    return [seed + i for i in range(DIMS)]


class Fake:
    """A MockTransport handler that records requests and answers like the embeddings API."""

    def __init__(self, statuses: list[int] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.statuses = list(statuses or [])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else 200
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "secret echo of the input"}})
        inputs = json.loads(request.content)["input"]
        data = [{"index": i, "embedding": _vector(float(len(text)))} for i, text in enumerate(inputs)]
        return httpx.Response(200, json={"data": list(reversed(data))})  # out of order on purpose


def _embedder(fake: Fake, **kw) -> AzureOpenAIEmbedder:
    return AzureOpenAIEmbedder(
        ENDPOINT, "emb", KEY, dimensions=DIMS, transport=httpx.MockTransport(fake), sleep=lambda s: None, **kw
    )


def test_request_shape_and_unit_normalised_vectors() -> None:
    fake = Fake()
    vector = _embedder(fake).embed("hello")
    request = fake.requests[0]
    assert request.url.path == "/openai/deployments/emb/embeddings"
    assert request.url.params["api-version"] == "2024-10-21"
    assert request.headers["api-key"] == KEY
    assert json.loads(request.content) == {"input": ["hello"], "dimensions": DIMS}
    assert len(vector) == DIMS and math.isclose(sum(v * v for v in vector), 1.0)


def test_results_follow_input_order_and_batches_are_bounded() -> None:
    fake = Fake()
    embedder = _embedder(fake)
    texts = [f"t{'x' * i}" for i in range(20)]
    vectors = embedder.embed_many(texts)
    assert len(fake.requests) == 2 and [len(json.loads(r.content)["input"]) for r in fake.requests] == [16, 4]
    assert vectors[0] != vectors[5]  # distinct inputs map to distinct vectors in the right order


def test_cache_avoids_a_second_call_and_prefetch_serves_documents() -> None:
    fake = Fake()
    embedder = _embedder(fake)
    embedder.embed("same")
    embedder.embed("same")
    assert len(fake.requests) == 1 and embedder.texts_sent == 1
    embedder.prefetch(["a title a title desc tag"])
    embedder.embed_document("a title", "desc", ("tag",))
    assert len(fake.requests) == 2


def test_retries_throttling_then_succeeds_but_not_client_errors() -> None:
    fake = Fake([429, 503])
    assert _embedder(fake).embed("x") and len(fake.requests) == 3
    bad = Fake([400])
    with pytest.raises(EmbeddingError, match="HTTP 400"):
        _embedder(bad).embed("x")
    assert len(bad.requests) == 1


def test_gives_up_after_bounded_retries() -> None:
    fake = Fake([500] * 10)
    with pytest.raises(EmbeddingError, match="after 4 attempts"):
        _embedder(fake, max_retries=3).embed("x")
    assert len(fake.requests) == 4


def test_errors_never_contain_the_input_the_key_or_the_response_body() -> None:
    for statuses in ([400], [500] * 10):
        with pytest.raises(EmbeddingError) as raised:
            _embedder(Fake(statuses), max_retries=1).embed("private query text")
        message = str(raised.value)
        assert "private query text" not in message and KEY not in message and "secret echo" not in message
    assert KEY not in repr(_embedder(Fake()))


def test_budget_cap_stops_further_calls() -> None:
    fake = Fake()
    embedder = _embedder(fake, max_texts=2)
    embedder.embed_many(["a", "b"])
    with pytest.raises(EmbeddingBudgetExceeded):
        embedder.embed("c")
    assert embedder.texts_sent == 2 and len(fake.requests) == 1


@pytest.mark.parametrize("bad", [[], [0.0] * DIMS, [float("nan")] * DIMS, [1.0] * (DIMS - 1)])
def test_unusable_embeddings_are_rejected(bad: list[float]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=json.dumps({"data": [{"index": 0, "embedding": bad}]}).replace("NaN", "null")
        )

    embedder = AzureOpenAIEmbedder(ENDPOINT, "emb", KEY, dimensions=DIMS, transport=httpx.MockTransport(handler))
    with pytest.raises(EmbeddingError):
        embedder.embed("x")


def test_constructor_rejects_unsafe_or_incomplete_settings() -> None:
    with pytest.raises(ValueError, match="https"):
        AzureOpenAIEmbedder("http://x", "emb", KEY)
    with pytest.raises(ValueError):
        AzureOpenAIEmbedder(ENDPOINT, "", KEY)
    with pytest.raises(ValueError, match="embeddable"):
        _embedder(Fake()).embed("   ")


# ---- configuration ----------------------------------------------------------------------------------------


def _azure(**over):
    base = {
        "no_model": False,
        "search_backend": "opensearch",
        "opensearch_url": "http://search.test:9200",
        "embedding_provider": "azure_openai",
        "azure_openai_endpoint": ENDPOINT,
        "azure_openai_deployment": "emb",
        "azure_openai_api_key": KEY,
    }
    base.update(over)
    return DiscoverySettings(**base)


def test_azure_provider_needs_a_model_an_index_https_and_credentials() -> None:
    assert _azure().embedding_provider == "azure_openai"
    with pytest.raises(ValueError, match="no_model"):
        _azure(no_model=True)
    with pytest.raises(ValueError, match="opensearch"):
        _azure(search_backend="memory", opensearch_url=None)
    with pytest.raises(ValueError, match="https"):
        _azure(azure_openai_endpoint="http://x")
    with pytest.raises(ValueError, match="deployment"):
        _azure(azure_openai_deployment=None)


def test_default_is_the_local_embedder_and_the_key_is_never_dumped() -> None:
    assert isinstance(create_embedder(DiscoverySettings()), HashingEmbedder)
    assert isinstance(create_embedder(_azure()), AzureOpenAIEmbedder)
    dump = _azure().redacted_dump()
    assert KEY not in str(dump) and "api_key" not in str(dump).lower() and dump["azure_openai_credential_set"] is True
    assert KEY not in repr(_azure())


def test_environment_variables_configure_the_provider() -> None:
    env = {
        "DISCOVERY_NO_MODEL": "false",
        "DISCOVERY_SEARCH_BACKEND": "opensearch",
        "DISCOVERY_OPENSEARCH_URL": "http://search.test:9200",
        "DISCOVERY_EMBEDDING_PROVIDER": "azure_openai",
        "DISCOVERY_AZURE_OPENAI_ENDPOINT": ENDPOINT,
        "DISCOVERY_AZURE_OPENAI_DEPLOYMENT": "emb",
        "DISCOVERY_AZURE_OPENAI_API_KEY": KEY,
        "DISCOVERY_EMBEDDING_DIMENSIONS": "384",
        "DISCOVERY_EMBEDDING_MAX_TEXTS": "50",
    }
    settings = settings_from_env(env)
    assert settings.embedding_provider == "azure_openai" and settings.embedding_max_texts == 50
    assert settings.environment is Environment.LOCAL


# ---- bootstrap guard -------------------------------------------------------------------------------------


def test_bootstrap_refuses_to_call_the_service_without_confirmation(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    for key, value in {
        "DISCOVERY_NO_MODEL": "false",
        "DISCOVERY_SEARCH_BACKEND": "opensearch",
        "DISCOVERY_OPENSEARCH_URL": "http://search.test:9200",
        "DISCOVERY_EMBEDDING_PROVIDER": "azure_openai",
        "DISCOVERY_AZURE_OPENAI_ENDPOINT": ENDPOINT,
        "DISCOVERY_AZURE_OPENAI_DEPLOYMENT": "emb",
        "DISCOVERY_AZURE_OPENAI_API_KEY": KEY,
    }.items():
        monkeypatch.setenv(key, value)
    called: list[int] = []
    monkeypatch.setattr(AzureOpenAIEmbedder, "_request", lambda self, batch: called.append(1) or [])
    assert bootstrap.main([]) == 2
    captured = capsys.readouterr()
    assert (
        "--confirm-spend" in captured.err
        and "texts in about" in captured.out
        and KEY not in captured.out + captured.err
    )
    assert called == []


# ---- search service ---------------------------------------------------------------------------------------


class Down:
    def lexical(self, *a, **k):
        raise OpenSearchUnavailable("down")

    vector = lexical


class Boom:
    model_version = "azure-openai-test"
    dimensions = DIMS

    def embed(self, text: str):
        raise EmbeddingError("service down")


def test_remote_query_vector_degrades_instead_of_raising() -> None:
    service = OpenSearchSearchService(Down(), (), (), remote_embedder=Boom())
    assert service._remote_query_vector("anything") is None


def test_fallback_when_the_cluster_is_down_is_lexical_only_and_never_calls_the_embedder() -> None:
    from app.config import FeatureFlags
    from app.demo_data import load_demo_catalog
    from app.routes.search import SearchRequest
    from packages.platform_contracts.discovery import DiscoveryRequestContext

    _, documents, users = load_demo_catalog()
    calls: list[str] = []

    class Counting(Boom):
        def embed(self, text: str):
            calls.append(text)
            raise EmbeddingError("must not be called")

    service = OpenSearchSearchService(
        Down(),
        documents,
        users,
        embedder=None,
        remote_embedder=Counting(),
        features=FeatureFlags(lexical=True, vector=True, hybrid=True),
    )
    request = SearchRequest(
        query="workshop",
        context=DiscoveryRequestContext(
            tenant_id="tenant-01",
            principal_id="user-0003",
            request_id="r1",
            purpose="search",
            locale="en-US",
            device="web",
            age=16,
        ),
    )
    response = service.search(request)

    assert response.fallback is True and response.error is None
    assert response.results and all("workshop" in r.title.lower() for r in response.results[:1])
    assert calls == []  # no billable call while the cluster is unreachable


# ---- managed identity / Azure CLI token authentication ---------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _token_embedder(fake: Fake, provider, **kw) -> AzureOpenAIEmbedder:
    return AzureOpenAIEmbedder(
        ENDPOINT,
        "emb",
        token_provider=provider,
        dimensions=DIMS,
        transport=httpx.MockTransport(fake),
        sleep=lambda s: None,
        **kw,
    )


def test_token_auth_sends_a_bearer_header_and_no_api_key() -> None:
    fake = Fake()
    _token_embedder(fake, lambda: "tok-1").embed("hello")
    headers = fake.requests[0].headers
    assert headers["authorization"] == "Bearer tok-1" and "api-key" not in headers


def test_the_token_is_cached_then_refreshed_after_the_ttl() -> None:
    fake, clock, issued = Fake(), Clock(), []

    def provider() -> str:
        issued.append(1)
        return f"tok-{len(issued)}"

    embedder = _token_embedder(fake, provider, clock=clock)
    embedder.embed("a")
    embedder.embed("b")
    assert len(issued) == 1
    clock.now += 1000
    embedder.embed("c")
    assert len(issued) == 2 and fake.requests[-1].headers["authorization"] == "Bearer tok-2"


def test_a_401_fetches_one_fresh_token_and_retries_once() -> None:
    fake, issued = Fake([401]), []

    def provider() -> str:
        issued.append(1)
        return f"tok-{len(issued)}"

    assert _token_embedder(fake, provider).embed("x")
    assert [r.headers["authorization"] for r in fake.requests] == ["Bearer tok-1", "Bearer tok-2"]


def test_a_403_names_the_missing_role_without_secrets_and_is_not_retried() -> None:
    fake = Fake([403])
    with pytest.raises(EmbeddingError) as raised:
        _token_embedder(fake, lambda: "tok-secret").embed("private query text")
    message = str(raised.value)
    assert "Cognitive Services OpenAI User" in message and "HTTP 403" in message
    assert "tok-secret" not in message and "private query text" not in message and "secret echo" not in message
    assert len(fake.requests) == 1


def test_a_persistent_401_stops_after_one_refresh() -> None:
    fake = Fake([401, 401, 401])
    with pytest.raises(EmbeddingError, match="HTTP 401"):
        _token_embedder(fake, lambda: "tok").embed("x")
    assert len(fake.requests) == 2


def test_a_missing_token_fails_before_any_request_with_a_clear_message() -> None:
    from app.ingest.store import StoreError

    def provider() -> str:
        raise StoreError("managed identity token request failed (HTTP 400)")

    fake = Fake()
    with pytest.raises(EmbeddingError, match="Entra token") as raised:
        _token_embedder(fake, provider).embed("x")
    assert fake.requests == [] and "HTTP 400" not in str(raised.value)


def test_exactly_one_credential_kind_is_required() -> None:
    with pytest.raises(ValueError, match="either"):
        AzureOpenAIEmbedder(ENDPOINT, "emb")
    with pytest.raises(ValueError, match="either"):
        AzureOpenAIEmbedder(ENDPOINT, "emb", KEY, token_provider=lambda: "t")


def test_token_providers_ask_for_the_cognitive_services_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.embedding.azure_openai import token_provider_for
    from app.ingest import store as store_module

    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost:42356/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "hdr")
    seen: list[httpx.Request] = []
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"access_token": "mi-token"})

    monkeypatch.setattr(
        store_module.httpx, "Client", lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handler)})
    )
    assert token_provider_for("managed_identity")() == "mi-token"
    assert seen[0].url.params["resource"] == "https://cognitiveservices.azure.com"

    calls: list[list[str]] = []

    class Done:
        returncode, stdout = 0, "cli-token\n"

    monkeypatch.setattr(store_module.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    assert token_provider_for("az_cli")() == "cli-token"
    assert calls[0][calls[0].index("--resource") + 1] == "https://cognitiveservices.azure.com"
    with pytest.raises(ValueError):
        token_provider_for("key")


def test_settings_validate_the_auth_mode() -> None:
    assert (
        _azure(azure_openai_api_key=None, azure_openai_auth="managed_identity").azure_openai_auth == "managed_identity"
    )
    assert _azure(azure_openai_api_key=None, azure_openai_auth="az_cli").azure_openai_auth == "az_cli"
    assert _azure().azure_openai_auth == "key"  # the default
    with pytest.raises(ValueError, match="needs an api key"):
        _azure(azure_openai_api_key=None)
    with pytest.raises(ValueError, match="api key is set"):
        _azure(azure_openai_auth="managed_identity")
    with pytest.raises(ValueError):
        _azure(azure_openai_auth="password")


def test_the_factory_builds_a_token_embedder_without_a_key_or_network() -> None:
    embedder = create_embedder(_azure(azure_openai_api_key=None, azure_openai_auth="managed_identity"))
    assert isinstance(embedder, AzureOpenAIEmbedder) and embedder.texts_sent == 0


def test_the_auth_mode_comes_from_the_environment() -> None:
    env = {
        "DISCOVERY_NO_MODEL": "false",
        "DISCOVERY_SEARCH_BACKEND": "opensearch",
        "DISCOVERY_OPENSEARCH_URL": "http://search.test:9200",
        "DISCOVERY_EMBEDDING_PROVIDER": "azure_openai",
        "DISCOVERY_AZURE_OPENAI_ENDPOINT": ENDPOINT,
        "DISCOVERY_AZURE_OPENAI_DEPLOYMENT": "emb",
        "DISCOVERY_AZURE_OPENAI_AUTH": "Managed_Identity",
    }
    assert settings_from_env(env).azure_openai_auth == "managed_identity"
    with pytest.raises(ValueError):
        settings_from_env({**env, "DISCOVERY_AZURE_OPENAI_AUTH": "nope"})
