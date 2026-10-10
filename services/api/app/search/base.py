from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.search.models import (
    BulkWriteResult,
    SearchDocument,
    SearchHealth,
    SearchIndexSpec,
    SearchRequest,
    SearchResponse,
    SearchScope,
)


@runtime_checkable
class EnterpriseSearchProvider(Protocol):
    """Provider-neutral lifecycle, indexing, deletion, and query contract."""

    async def connect(self) -> None:
        """Open provider resources and validate connectivity."""
        ...

    async def close(self) -> None:
        """Release provider resources."""
        ...

    async def health(self) -> SearchHealth:
        """Return provider and active-index health without exposing raw payloads."""
        ...

    async def ensure_index(self, spec: SearchIndexSpec) -> None:
        """Create or validate a physical index for a versioned schema."""
        ...

    async def activate_alias(self, alias: str, index_name: str) -> None:
        """Atomically point a stable alias at a physical index generation."""
        ...

    async def upsert(
        self,
        documents: Sequence[SearchDocument],
        *,
        index: str | None = None,
    ) -> BulkWriteResult:
        """Idempotently write canonical documents to the derived index."""
        ...

    async def delete(
        self,
        document_ids: Sequence[str],
        *,
        scope: SearchScope,
        index: str | None = None,
    ) -> BulkWriteResult:
        """Delete documents only inside the caller's tenant scope."""
        ...

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute a scoped lexical, vector, or hybrid search request."""
        ...
