"""Search service that ranks through OpenSearch and degrades to the in-memory catalog."""

from __future__ import annotations

from app.candidates.contracts import CandidateSourceResult
from app.domain.models import ImmersiveDiscoveryContext, UserProfile
from app.embedding.azure_openai import EmbeddingError
from app.opensearch.client import OpenSearchError, OpenSearchUnavailable
from app.opensearch.retriever import OpenSearchRetriever
from app.routes.search import _VECTOR_K, LocalSearchService, Retrieval, _drop_weak_vector
from app.search.vector import VectorQuery


class OpenSearchSearchService(LocalSearchService):
    """Use the cluster when it answers; otherwise serve the in-memory catalog and mark the response degraded.

    The in-memory catalog is the same generated data the index was loaded from, so the fallback keeps
    the demo usable while an on-demand cluster is stopped.
    """

    def __init__(self, retriever: OpenSearchRetriever, *args, remote_embedder=None, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """``remote_embedder`` embeds queries for the cluster's vectors when they differ from the in-memory ones
        (for example Azure OpenAI vectors in the index). The in-memory fallback is then lexical only, because
        its vectors come from the local embedder and would not be comparable."""
        super().__init__(*args, **kwargs)
        self._remote = retriever
        self._remote_embedder = remote_embedder if remote_embedder is not None else kwargs.get("embedder")

    @property
    def _remote_wants_vector(self) -> bool:
        return self._remote_embedder is not None and (self._features.vector or self._features.hybrid)

    def _remote_query_vector(self, text: str) -> VectorQuery | None:
        embedder = self._remote_embedder
        try:
            return VectorQuery(
                embedding=embedder.embed(text),
                embedding_model_version=embedder.model_version,
                dimensions=embedder.dimensions,
            )
        except (ValueError, EmbeddingError):
            return None

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
            if self._remote_wants_vector:
                query = self._remote_query_vector(text)
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
