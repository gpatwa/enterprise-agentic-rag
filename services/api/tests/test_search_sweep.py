"""Stale file-chunk finder: query shape, pins and refusals, against a recording fake client (no cluster)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.search.opensearch import OpenSearchProvider
from app.search.schema import ingest_run_tag
from app.search.sweep import (
    SweepRefused,
    check_hit,
    run_files_query,
    stale_chunks_query,
    validate_sweep_inputs,
)

STARTED = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
RUN = "job-7"
TAG = "ingest-run:job-7"


def _config():
    return SimpleNamespace(
        OPENSEARCH_INDEX_ALIAS="support-search",
        OPENSEARCH_URL="http://localhost:9200",
        OPENSEARCH_MAX_RETRIES=0,
        get_opensearch_url=lambda: "http://localhost:9200",
    )


class Indices:
    def __init__(self):
        self.refreshed = []

    async def refresh(self, *, index):
        self.refreshed.append(index)


class Client:
    """Scripted responses for ``search``: file aggregation pages first, then stale-chunk pages."""

    def __init__(self, file_pages, stale_pages):
        self.indices = Indices()
        self.file_pages, self.stale_pages = list(file_pages), list(stale_pages)
        self.searches = []
        self.deletes = []

    async def info(self):
        return {"version": {"number": "2.15.0"}}

    async def search(self, *, index, body):
        self.searches.append((index, body))
        if "aggs" in body:
            return self.file_pages.pop(0)
        return self.stale_pages.pop(0)

    async def delete_by_query(self, **kwargs):  # the finder must never delete
        self.deletes.append(kwargs)
        raise AssertionError("find_stale_file_chunks must not delete")

    async def close(self):
        pass


def _files(*names, after=None):
    return {
        "aggregations": {
            "files": {"buckets": [{"key": {"file": n}} for n in names], **({"after_key": after} if after else {})}
        }
    }


def _hit(doc_id, *, tenant="acme", provider="ray-ingest", source_type="file_chunk", tags=()):
    return {
        "_source": {
            "document_id": doc_id,
            "tenant_id": tenant,
            "provider": provider,
            "source_type": source_type,
            "tags": list(tags),
        },
        "sort": [doc_id],
    }


def _hits(*hits):
    return {"hits": {"hits": list(hits)}}


async def _find(client, **kw):
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()
    args = dict(
        index="chunks-1",
        tenant_id="acme",
        provider_name="ray-ingest",
        run_id=RUN,
        run_started_at=STARTED,
        max_documents=100,
        page_size=2,
    )
    args.update(kw)
    return await provider.find_stale_file_chunks(**args)


def _filters(body):
    return body["query"]["bool"]["filter"]


# ----- query shape --------------------------------------------------------------------------------------------


def test_every_query_is_pinned_to_tenant_provider_and_file_chunk() -> None:
    pins = [
        {"term": {"tenant_id": "acme"}},
        {"term": {"provider": "ray-ingest"}},
        {"term": {"source_type": "file_chunk"}},
    ]
    files = run_files_query("acme", "ray-ingest", TAG, None)
    assert _filters(files)[:3] == pins and {"term": {"tags": TAG}} in _filters(files)
    stale = stale_chunks_query("acme", "ray-ingest", TAG, STARTED, ["a.pdf"], page_size=10, search_after=None)
    assert _filters(stale)[:3] == pins
    assert {"terms": {"title.keyword": ["a.pdf"]}} in _filters(stale)
    assert stale["query"]["bool"]["must_not"] == [{"term": {"tags": TAG}}]


def test_the_time_guard_spares_chunks_written_after_the_run_began_and_counts_unstamped_ones_as_older() -> None:
    stale = stale_chunks_query("acme", "ray-ingest", TAG, STARTED, ["a.pdf"], page_size=10, search_after=None)
    should = stale["query"]["bool"]["should"]
    assert {"range": {"updated_at": {"lt": "2026-11-06T12:00:00+00:00"}}} in should
    assert {"bool": {"must_not": [{"exists": {"field": "updated_at"}}]}} in should
    assert stale["query"]["bool"]["minimum_should_match"] == 1


# ----- refusals ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("index", ["", "*", "chunks-*", "a,b", "_all", ".kibana", "Chunks", "a b", None])
def test_only_one_concrete_index_name_is_accepted(index) -> None:
    with pytest.raises(SweepRefused):
        validate_sweep_inputs(
            index=index, tenant_id="acme", provider_name="p", run_id=RUN, run_started_at=STARTED, max_documents=1
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": ""},
        {"tenant_id": " acme"},
        {"provider_name": "  "},
        {"run_id": ""},
        {"run_id": "bad id"},
        {"run_started_at": datetime(2026, 11, 6)},
        {"max_documents": 0},
        {"max_documents": True},
    ],
)
def test_blank_or_malformed_inputs_are_refused_before_any_query(overrides) -> None:
    base = dict(
        index="chunks-1", tenant_id="acme", provider_name="p", run_id=RUN, run_started_at=STARTED, max_documents=5
    )
    with pytest.raises(SweepRefused):
        validate_sweep_inputs(**{**base, **overrides})


def test_the_run_tag_is_the_prefix_plus_the_id() -> None:
    assert ingest_run_tag("job-7") == TAG
    with pytest.raises(ValueError):
        ingest_run_tag("../x")


@pytest.mark.parametrize(
    "hit",
    [
        _hit("d", tenant="other"),
        _hit("d", provider="postgres-sync"),
        _hit("d", source_type="ticket_chunk"),
        _hit("d", tags=[TAG]),
        {"_source": None},
        {"_source": {"tenant_id": "acme", "provider": "ray-ingest", "source_type": "file_chunk"}},
    ],
)
def test_a_hit_outside_the_pins_is_refused_whatever_the_query_returned(hit) -> None:
    with pytest.raises(SweepRefused):
        check_hit(hit["_source"], tenant_id="acme", provider_name="ray-ingest", run_tag=TAG)


# ----- the finder against a scripted client -------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_lists_stale_ids_for_the_files_the_run_wrote_and_pages_through_results() -> None:
    client = Client(
        file_pages=[_files("a.pdf", "b.pdf")],
        stale_pages=[_hits(_hit("d1"), _hit("d2")), _hits(_hit("d3"))],
    )
    result = await _find(client)
    assert result.document_ids == ("d1", "d2", "d3") and result.files == ("a.pdf", "b.pdf")
    assert client.indices.refreshed == ["chunks-1"]
    assert client.deletes == []
    second_stale = client.searches[2][1]
    assert second_stale["search_after"] == ["d2"]
    assert {"terms": {"title.keyword": ["a.pdf", "b.pdf"]}} in _filters(second_stale)


@pytest.mark.asyncio
async def test_a_run_that_wrote_nothing_sweeps_nothing_and_never_searches_for_stale_chunks() -> None:
    client = Client(file_pages=[_files()], stale_pages=[])
    result = await _find(client)
    assert result.document_ids == () and result.files == ()
    assert len(client.searches) == 1  # only the file aggregation


@pytest.mark.asyncio
async def test_file_pages_are_followed_with_the_after_key() -> None:
    client = Client(
        file_pages=[_files("a.pdf", after={"file": "a.pdf"}), _files("b.pdf")],
        stale_pages=[_hits()],
    )
    result = await _find(client)
    assert result.files == ("a.pdf", "b.pdf")
    assert client.searches[1][1]["aggs"]["files"]["composite"]["after"] == {"file": "a.pdf"}


@pytest.mark.asyncio
async def test_more_stale_chunks_than_the_cap_is_refused_with_nothing_returned() -> None:
    client = Client(file_pages=[_files("a.pdf")], stale_pages=[_hits(_hit("d1"), _hit("d2")), _hits(_hit("d3"))])
    with pytest.raises(SweepRefused, match="more than 2 chunks"):
        await _find(client, max_documents=2)


@pytest.mark.asyncio
async def test_a_foreign_document_in_the_results_aborts_the_whole_sweep() -> None:
    client = Client(file_pages=[_files("a.pdf")], stale_pages=[_hits(_hit("d1"), _hit("d2", tenant="beta"))])
    with pytest.raises(SweepRefused, match="outside the sweep"):
        await _find(client)


@pytest.mark.asyncio
async def test_a_missing_aggregation_is_refused_rather_than_read_as_no_files() -> None:
    client = Client(file_pages=[{"hits": {"hits": []}}], stale_pages=[])
    with pytest.raises(SweepRefused, match="no file aggregation"):
        await _find(client)


@pytest.mark.asyncio
async def test_an_unusable_index_name_is_refused_before_the_cluster_is_touched() -> None:
    client = Client(file_pages=[], stale_pages=[])
    with pytest.raises(SweepRefused):
        await _find(client, index="chunks-*")
    assert client.searches == [] and client.indices.refreshed == []
