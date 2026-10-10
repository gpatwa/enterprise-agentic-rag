from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.search.opensearch import OpenSearchProvider


def _config(**overrides):
    values = {
        "OPENSEARCH_INDEX_ALIAS": "support-search",
        "OPENSEARCH_URL": "https://search.internal:9200",
        "OPENSEARCH_PORT": 9200,
        "OPENSEARCH_VERIFY_CERTS": True,
        "OPENSEARCH_CA_CERT_PATH": "/etc/certs/search-ca.pem",
        "OPENSEARCH_REQUEST_TIMEOUT_SECONDS": 10.0,
        "OPENSEARCH_MAX_RETRIES": 3,
        "OPENSEARCH_RETRY_ON_TIMEOUT": True,
        "OPENSEARCH_POOL_MAXSIZE": 8,
        "OPENSEARCH_AUTH_MODE": "basic",
        "OPENSEARCH_USERNAME": "search-user",
        "OPENSEARCH_PASSWORD": "search-password",
        "get_opensearch_url": lambda: "https://search.internal:9200",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeCluster:
    def __init__(self, response):
        self.response = response

    async def health(self):
        return self.response


class FakeClient:
    def __init__(self, *, info_response=None, cluster_response=None, info_error=None):
        self.info_response = info_response or {"version": {"number": "2.15.0"}}
        self.cluster = FakeCluster(cluster_response or {"status": "green", "number_of_nodes": 3})
        self.info_error = info_error
        self.closed = False
        self.info_calls = 0
        self.indices = None
        self.bulk_calls = []
        self.bulk_response = {"errors": False, "items": []}
        self.mget_calls = []
        self.mget_response = {"docs": []}

    async def info(self):
        self.info_calls += 1
        if self.info_error:
            raise self.info_error
        return self.info_response

    async def close(self):
        self.closed = True

    async def count(self, *, index):
        return {"count": getattr(self, "count_response", 0)}

    async def bulk(self, *, index, body):
        self.bulk_calls.append({"index": index, "body": body})
        return self.bulk_response

    async def mget(self, *, index, body):
        self.mget_calls.append({"index": index, "body": body})
        return self.mget_response


@pytest.mark.asyncio
async def test_health_is_not_ready_before_connect():
    provider = OpenSearchProvider(config=_config(), client=FakeClient())

    health = await provider.health()

    assert health.status == "not_ready"
    assert health.index_alias == "support-search"
    assert health.details["connected"] is False


@pytest.mark.asyncio
async def test_connect_health_and_close_use_async_client():
    client = FakeClient(
        cluster_response={
            "status": "yellow",
            "cluster_name": "support-search",
            "number_of_nodes": 2,
            "active_shards": 4,
            "unassigned_shards": 1,
        }
    )
    provider = OpenSearchProvider(config=_config(), client=client)

    await provider.connect()
    health = await provider.health()
    await provider.close()

    assert client.info_calls == 1
    assert health.status == "ready"
    assert health.details["cluster_status"] == "yellow"
    assert health.details["version"] == "2.15.0"
    assert client.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [(PermissionError("unauthorized"), "auth"), (TimeoutError("timed out"), "timeout")],
)
async def test_connect_normalizes_authentication_and_timeout_failures(error, code):
    from app.search.errors import OpenSearchError

    provider = OpenSearchProvider(
        config=_config(),
        client=FakeClient(info_error=error),
    )

    with pytest.raises(OpenSearchError) as raised:
        await provider.connect()

    assert raised.value.code == code
    assert raised.value.operation == "connect"


class StatusError(Exception):
    def __init__(self, status_code, *, info=None):
        super().__init__(f"status {status_code}")
        self.status_code = status_code
        self.info = info


class SequenceClient(FakeClient):
    def __init__(self, errors):
        super().__init__()
        self.errors = list(errors)

    async def info(self):
        self.info_calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.info_response


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (StatusError(401), "auth", False),
        (
            StatusError(400, info={"error": {"type": "mapper_parsing_exception"}}),
            "mapping",
            False,
        ),
        (StatusError(429), "throttled", True),
        (TimeoutError("request timed out"), "timeout", True),
        (StatusError(503), "unavailable", True),
    ],
)
def test_opensearch_errors_normalize_deterministically(error, code, retryable):
    from app.search.errors import normalize_opensearch_exception

    normalized = normalize_opensearch_exception(error, operation="search")

    assert normalized.code == code
    assert normalized.retryable is retryable
    assert normalized.operation == "search"
    assert normalized.cause is error


@pytest.mark.asyncio
async def test_provider_wraps_transport_errors_with_operation_context():
    from app.search.errors import OpenSearchError

    error = StatusError(503)
    provider = OpenSearchProvider(config=_config(), client=FakeClient(info_error=error))

    with pytest.raises(OpenSearchError) as raised:
        await provider.connect()

    assert raised.value.code == "unavailable"
    assert raised.value.operation == "connect"


@pytest.mark.asyncio
async def test_retryable_errors_use_bounded_exponential_backoff(monkeypatch):
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("app.search.opensearch.asyncio.sleep", fake_sleep)
    client = SequenceClient([StatusError(503), StatusError(503)])
    provider = OpenSearchProvider(config=_config(OPENSEARCH_MAX_RETRIES=2), client=client)

    await provider.connect()

    assert client.info_calls == 3
    assert delays == [0.1, 0.2]


@pytest.mark.asyncio
async def test_retryable_errors_stop_at_configured_bound(monkeypatch):
    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr("app.search.opensearch.asyncio.sleep", fake_sleep)
    client = SequenceClient([StatusError(503), StatusError(503), StatusError(503), StatusError(503)])
    provider = OpenSearchProvider(config=_config(OPENSEARCH_MAX_RETRIES=2), client=client)

    from app.search.errors import OpenSearchError

    with pytest.raises(OpenSearchError) as raised:
        await provider.connect()

    assert raised.value.code == "unavailable"
    assert client.info_calls == 3


@pytest.mark.asyncio
async def test_nonretryable_error_runs_once(monkeypatch):
    async def fail_if_called(_delay):
        raise AssertionError("nonretryable error should not sleep")

    monkeypatch.setattr("app.search.opensearch.asyncio.sleep", fail_if_called)
    client = SequenceClient([StatusError(401), StatusError(401)])
    provider = OpenSearchProvider(config=_config(OPENSEARCH_MAX_RETRIES=3), client=client)

    from app.search.errors import OpenSearchError

    with pytest.raises(OpenSearchError) as raised:
        await provider.connect()

    assert raised.value.code == "auth"
    assert client.info_calls == 1


@pytest.mark.asyncio
async def test_circuit_breaker_blocks_after_repeated_exhausted_failures(monkeypatch):
    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr("app.search.opensearch.asyncio.sleep", fake_sleep)
    client = SequenceClient([StatusError(503), StatusError(503), StatusError(503)])
    provider = OpenSearchProvider(config=_config(OPENSEARCH_MAX_RETRIES=0), client=client)
    provider.CIRCUIT_FAILURE_THRESHOLD = 2

    from app.search.errors import OpenSearchError

    for _ in range(2):
        with pytest.raises(OpenSearchError):
            await provider.connect()

    with pytest.raises(OpenSearchError) as raised:
        await provider.connect()

    assert raised.value.code == "circuit_open"
    assert client.info_calls == 2


class FakeIndices:
    def __init__(self, *, exists=False, mapping=None, aliases=None, update_error=None):
        self.exists_response = exists
        self.mapping = mapping
        self.aliases = aliases or {}
        self.update_error = update_error
        self.created = []
        self.get_mapping_calls = 0
        self.alias_updates = []

    async def exists(self, *, index):
        return self.exists_response

    async def create(self, *, index, body):
        self.created.append((index, body))

    async def get_mapping(self, *, index):
        self.get_mapping_calls += 1
        return {index: {"mappings": self.mapping}}

    async def get_alias(self, *, name):
        if not self.aliases:
            raise StatusError(404)
        return self.aliases

    async def update_aliases(self, *, body):
        if self.update_error:
            raise self.update_error
        self.alias_updates.append(body)
        for action in body["actions"]:
            if "remove" in action:
                remove = action["remove"]
                self.aliases.get(remove["index"], {}).get("aliases", {}).pop(remove["alias"], None)
            else:
                add = action["add"]
                self.aliases.setdefault(add["index"], {"aliases": {}})["aliases"][add["alias"]] = {
                    "is_write_index": add["is_write_index"]
                }

@pytest.mark.asyncio
async def test_health_reports_active_generation_mapping_model_count_and_alias_state():
    from app.search.mappings import SUPPORT_SEARCH_MAPPING_VERSION, build_support_index_definition

    mapping = build_support_index_definition(768)["mappings"]
    mapping["_meta"] = {
        "mapping_version": SUPPORT_SEARCH_MAPPING_VERSION,
        "schema_version": "support-search-v1",
        "embedding_model_version": "embed-v1",
    }
    client = FakeClient()
    client.count_response = 42
    client.indices = FakeIndices(
        exists=True,
        mapping=mapping,
        aliases={"support-search-v2": {"aliases": {"support-search": {"is_write_index": True}}}},
    )
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    health = await provider.health()

    assert health.status == "ready"
    assert health.index_generation == "support-search-v2"
    assert health.document_count == 42
    assert health.details["mapping_version"] == SUPPORT_SEARCH_MAPPING_VERSION
    assert health.details["model"] == "embed-v1"
    assert health.details["alias_state"] == {
        "alias": "support-search",
        "status": "active",
        "indexes": ["support-search-v2"],
        "write_index": "support-search-v2",
    }


@pytest.mark.asyncio
async def test_health_is_not_ready_when_search_alias_is_missing():
    client = FakeClient()
    client.indices = FakeIndices(exists=True, aliases={})
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    health = await provider.health()

    assert health.status == "not_ready"
    assert health.index_generation is None
    assert health.document_count == 0
    assert health.details["alias_state"]["status"] == "missing"


@pytest.mark.asyncio
async def test_activate_alias_creates_alias_for_known_index():
    client = FakeClient()
    client.indices = FakeIndices(exists=True)
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    await provider.activate_alias("support-search", "support-search-v1")

    assert client.indices.alias_updates == [
        {
            "actions": [
                {
                    "add": {
                        "index": "support-search-v1",
                        "alias": "support-search",
                        "is_write_index": True,
                    }
                }
            ]
        }
    ]


@pytest.mark.asyncio
async def test_activate_alias_swaps_generation_in_one_atomic_request():
    client = FakeClient()
    client.indices = FakeIndices(
        exists=True,
        aliases={"support-search-v1": {"aliases": {"support-search": {}}}},
    )
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    await provider.activate_alias("support-search", "support-search-v2")

    assert client.indices.alias_updates[0] == {
        "actions": [
            {"remove": {"index": "support-search-v1", "alias": "support-search"}},
            {
                "add": {
                    "index": "support-search-v2",
                    "alias": "support-search",
                    "is_write_index": True,
                }
            },
        ]
    }
    assert "support-search" not in client.indices.aliases["support-search-v1"]["aliases"]
    assert client.indices.aliases["support-search-v2"]["aliases"]["support-search"]["is_write_index"] is True


@pytest.mark.asyncio
async def test_activate_alias_failure_preserves_previous_target():
    from app.search.errors import OpenSearchError

    previous = {"support-search-v1": {"aliases": {"support-search": {}}}}
    client = FakeClient()
    client.indices = FakeIndices(exists=True, aliases=previous, update_error=StatusError(503))
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    with pytest.raises(OpenSearchError) as raised:
        await provider.activate_alias("support-search", "support-search-v2")

    assert raised.value.code == "unavailable"
    assert client.indices.aliases == previous


@pytest.mark.asyncio
async def test_ensure_index_creates_versioned_physical_index():
    client = FakeClient()
    client.indices = FakeIndices()
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    from app.search.models import SearchIndexSpec

    await provider.ensure_index(
        SearchIndexSpec(
            alias="support-search",
            generation="support-search-v1",
            schema_version="support-search-v1",
            vector_dimensions=768,
            embedding_model_version="embed-v1",
        )
    )

    assert len(client.indices.created) == 1
    index_name, definition = client.indices.created[0]
    assert index_name == "support-search-v1"
    assert definition["mappings"]["properties"]["embedding"]["dimension"] == 768
    assert definition["mappings"]["_meta"]["schema_version"] == "support-search-v1"


def _search_document(document_id: str, *, vector=(0.1, 0.2, 0.3)):
    from app.search.models import SearchDocument

    return SearchDocument(
        document_id=document_id,
        tenant_id="tenant-a",
        source_type="ticket",
        source_id=document_id,
        provider="zendesk",
        title="Export timeout",
        text="Restart the export worker.",
        metadata={"status": "open"},
        acl_tokens=["tenant:tenant-a"],
        vector=vector,
        content_version="v1",
        permission_version="acl-v1",
    )


@pytest.mark.asyncio
async def test_upsert_builds_idempotent_bulk_actions_and_deduplicates_inputs():
    client = FakeClient()
    client.bulk_response = {
        "errors": False,
        "items": [
            {"index": {"status": 201}},
            {"index": {"status": 200}},
        ],
    }
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    result = await provider.upsert(
        [_search_document("doc-1"), _search_document("doc-1"), _search_document("doc-2")],
        index="support-search-v1",
    )

    assert result.attempted == 2
    assert result.succeeded == 2
    assert result.failed == 0
    assert len(client.bulk_calls) == 1
    assert client.bulk_calls[0]["index"] == "support-search-v1"
    assert [client.bulk_calls[0]["body"][i]["index"]["_id"] for i in (0, 2)] == ["doc-1", "doc-2"]
    assert client.bulk_calls[0]["body"][1]["embedding"] == [0.1, 0.2, 0.3]
    assert client.bulk_calls[0]["body"][1]["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_upsert_reports_partial_failures_without_replaying_successes():
    client = FakeClient()
    client.bulk_response = {
        "errors": True,
        "items": [
            {"index": {"status": 201}},
            {
                "index": {
                    "status": 429,
                    "error": {"type": "es_rejected_execution_exception", "reason": "busy"},
                }
            },
            {
                "index": {
                    "status": 400,
                    "error": {"type": "mapper_parsing_exception", "reason": "bad vector"},
                }
            },
        ],
    }
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    result = await provider.upsert(
        [_search_document("doc-1"), _search_document("doc-2"), _search_document("doc-3")]
    )

    assert result.attempted == 3
    assert result.succeeded == 1
    assert result.failed == 2
    assert [error.document_id for error in result.errors] == ["doc-2", "doc-3"]
    assert result.errors[0].code == "throttled"
    assert result.errors[0].retryable is True
    assert result.errors[1].code == "mapping"
    assert result.errors[1].retryable is False
    assert len(client.bulk_calls) == 1


@pytest.mark.asyncio
async def test_delete_is_tenant_scoped_and_acknowledges_missing_tombstones():
    from app.search.models import SearchScope

    client = FakeClient()
    client.mget_response = {
        "docs": [
            {"_id": "doc-a", "found": True, "_source": {"tenant_id": "tenant-a"}},
            {"_id": "doc-b", "found": True, "_source": {"tenant_id": "tenant-b"}},
            {"_id": "doc-missing", "found": False},
        ]
    }
    client.bulk_response = {
        "errors": False,
        "items": [{"delete": {"status": 200}}, {"delete": {"status": 404}}],
    }
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    result = await provider.delete(
        ["doc-a", "doc-b", "doc-missing"],
        scope=SearchScope(
            tenant_id="tenant-a",
            principal_id="user-1",
            purpose="test-delete",
            acl_tokens=["tenant:tenant-a"],
        ),
    )

    assert result.attempted == 3
    assert result.succeeded == 2
    assert result.failed == 1
    assert result.errors[0].document_id == "doc-b"
    assert result.errors[0].code == "tenant_scope"
    assert [item["delete"]["_id"] for item in client.bulk_calls[0]["body"]] == [
        "doc-a",
        "doc-missing",
    ]


@pytest.mark.asyncio
async def test_delete_replay_is_idempotent_for_missing_document():
    from app.search.models import SearchScope

    client = FakeClient()
    client.mget_response = {
        "docs": [{"_id": "doc-a", "found": True, "_source": {"tenant_id": "tenant-a"}}]
    }
    client.bulk_response = {"errors": False, "items": [{"delete": {"status": 200}}]}
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()
    scope = SearchScope(
        tenant_id="tenant-a",
        principal_id="user-1",
        purpose="test-delete",
        acl_tokens=["tenant:tenant-a"],
    )

    first = await provider.delete(["doc-a", "doc-a"], scope=scope)
    client.mget_response = {"docs": [{"_id": "doc-a", "found": False}]}
    client.bulk_response = {"errors": False, "items": [{"delete": {"status": 404}}]}
    second = await provider.delete(["doc-a"], scope=scope)

    assert first.succeeded == 1
    assert second.succeeded == 1
    assert second.failed == 0
    assert len(client.bulk_calls) == 2


@pytest.mark.asyncio
async def test_delete_fails_closed_on_incomplete_scope_lookup():
    from app.search.models import SearchScope

    client = FakeClient()
    client.mget_response = {
        "docs": [{"_id": "doc-a", "found": True, "_source": {"tenant_id": "tenant-a"}}]
    }
    client.bulk_response = {"errors": False, "items": [{"delete": {"status": 200}}]}
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()
    scope = SearchScope(
        tenant_id="tenant-a",
        principal_id="user-1",
        purpose="test-delete",
        acl_tokens=["tenant:tenant-a"],
    )

    result = await provider.delete(["doc-a", "doc-unknown"], scope=scope)

    assert result.succeeded == 1
    assert result.failed == 1
    assert result.errors[0].code == "scope_lookup"
    assert [item["delete"]["_id"] for item in client.bulk_calls[0]["body"]] == ["doc-a"]


@pytest.mark.asyncio
async def test_ensure_index_is_idempotent_for_matching_mapping():
    from app.search.mappings import SUPPORT_SEARCH_MAPPING_VERSION, build_support_index_definition
    from app.search.models import SearchIndexSpec

    expected = build_support_index_definition(768)
    expected["mappings"]["_meta"] = {
        "mapping_version": SUPPORT_SEARCH_MAPPING_VERSION,
        "schema_version": "support-search-v1",
        "embedding_model_version": "embed-v1",
    }
    client = FakeClient()
    client.indices = FakeIndices(exists=True, mapping=expected["mappings"])
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    await provider.ensure_index(
        SearchIndexSpec(
            alias="support-search",
            generation="support-search-v1",
            schema_version="support-search-v1",
            vector_dimensions=768,
            embedding_model_version="embed-v1",
        )
    )

    assert client.indices.created == []
    assert client.indices.get_mapping_calls == 1


@pytest.mark.asyncio
async def test_ensure_index_rejects_incompatible_existing_mapping():
    from app.search.mappings import build_support_index_definition
    from app.search.models import SearchIndexSpec

    existing = build_support_index_definition(1536)["mappings"]
    client = FakeClient()
    client.indices = FakeIndices(exists=True, mapping=existing)
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    with pytest.raises(ValueError, match="support-search-v1.*incompatible mapping"):
        await provider.ensure_index(
            SearchIndexSpec(
                alias="support-search",
                generation="support-search-v1",
                schema_version="support-search-v1",
                vector_dimensions=768,
                embedding_model_version="embed-v1",
            )
        )


def test_client_options_include_tls_and_basic_auth():
    provider = OpenSearchProvider(config=_config())

    options = provider._client_options()

    assert options["hosts"] == [{"host": "search.internal", "port": 9200}]
    assert options["use_ssl"] is True
    assert options["verify_certs"] is True
    assert options["ca_certs"] == "/etc/certs/search-ca.pem"
    assert options["http_auth"] == ("search-user", "search-password")
    assert options["max_retries"] == 3


def test_client_options_use_api_key_header():
    provider = OpenSearchProvider(
        config=_config(
            OPENSEARCH_AUTH_MODE="api_key",
            OPENSEARCH_USERNAME=None,
            OPENSEARCH_PASSWORD=None,
            OPENSEARCH_API_KEY="encoded-key",
        )
    )

    assert provider._client_options()["headers"] == {"Authorization": "ApiKey encoded-key"}
