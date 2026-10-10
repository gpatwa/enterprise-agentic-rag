import pytest


@pytest.mark.asyncio
async def test_shadow_comparison_returns_primary_and_never_leaks_text():
    from app.search.models import RetrievalSource, SearchResponse, SearchResult
    from app.search.shadow import search_with_shadow

    def response(ids):
        return SearchResponse(
            results=tuple(
                SearchResult(
                    document_id=document_id,
                    tenant_id="tenant-acme",
                    source_type="ticket",
                    source_id=document_id,
                    title="title",
                    text="sensitive body",
                    score=1.0,
                    rank=rank,
                    retrieval_source=RetrievalSource.LEXICAL,
                    index_generation="g1",
                    content_version="v1",
                    permission_version="p1",
                )
                for rank, document_id in enumerate(ids, 1)
            ),
            index_alias="alias",
            index_generation="g1",
        )

    class Provider:
        def __init__(self, result):
            self.result = result

        async def search(self, request):
            return self.result

    events = []
    primary, comparison = await search_with_shadow(
        Provider(response(["a", "b"])),
        Provider(response(["b", "c"])),
        object(),
        event_sink=lambda name, values: events.append((name, values)),
    )
    assert [item.document_id for item in primary.results] == ["a", "b"]
    assert comparison.overlap_at_k == 0.5
    assert events[0][1]["rank_deltas"] == (-1,)
    assert "sensitive body" not in str(events)
