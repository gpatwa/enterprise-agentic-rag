"""Search service that ranks through OpenSearch and degrades to the in-memory catalog."""

from __future__ import annotations

from app.candidates.contracts import CandidateSourceResult
from app.domain.models import ImmersiveDiscoveryContext, UserProfile
from app.opensearch.client import OpenSearchError, OpenSearchUnavailable
from app.opensearch.retriever import OpenSearchRetriever
from app.routes.search import _VECTOR_K, LocalSearchService, Retrieval, _drop_weak_vector


class OpenSearchSearchService(LocalSearchService):
    """Use the cluster when it answers; otherwise serve the in-memory catalog and mark the response degraded.

    The in-memory catalog is the same generated data the index was loaded from, so the fallback keeps
    the demo usable while an on-demand cluster is stopped.
    """

    def __init__(self, retriever: OpenSearchRetriever, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._remote = retriever

    def _retrieve(self, text: str, context: ImmersiveDiscoveryContext, profile: UserProfile | None) -> Retrieval:
        sources: list[CandidateSourceResult] = []
        evidence: dict[str, tuple[str, ...]] = {}
        titles: dict[str, str] = {}
        fallback = False
        try:
            if self._features.lexical:
                lexical, lexical_titles = self._remote.lexical(text, context, profile)
                sources.append(lexical.source_result)
                evidence.update({item.experience_id: item.matched_fields for item in lexical.evidence})
                titles.update(lexical_titles)
            if self._wants_vector:
                query = self._query_vector(text)
                if query is None:
                    fallback = True
                else:
                    vector, vector_titles = self._remote.vector(query, context, profile, k=_VECTOR_K)
                    sources.append(_drop_weak_vector(vector.source_result))
                    for item in vector.evidence:
                        evidence.setdefault(item.experience_id, ("embedding",))
                    titles.update(vector_titles)
        except (OpenSearchUnavailable, OpenSearchError):
            local = super()._retrieve(text, context, profile)
            return Retrieval(local.sources, local.evidence, local.titles, local.pool, fallback=True)
        return Retrieval(tuple(sources), evidence, titles, pool=len(titles), fallback=fallback)
