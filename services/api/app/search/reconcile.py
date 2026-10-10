from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.search.backfill import iter_source_documents
from app.search.schema import SUPPORT_SEARCH_SCHEMA_VERSION, SupportSearchDocument


@dataclass
class ReconciliationReport:
    tenant_id: str
    source_count: int = 0
    index_count: int = 0
    missing_count: int = 0
    extra_count: int = 0
    stale_count: int = 0
    acl_mismatched_count: int = 0
    version_mismatched_count: int = 0
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    acl_mismatched: tuple[str, ...] = ()
    version_mismatched: tuple[str, ...] = ()
    _sample_limit: int = field(default=100, repr=False)

    @property
    def mismatch_count(self) -> int:
        return sum(
            (
                self.missing_count,
                self.extra_count,
                self.stale_count,
                self.acl_mismatched_count,
                self.version_mismatched_count,
            )
        )

    @property
    def clean(self) -> bool:
        return self.mismatch_count == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "source_count": self.source_count,
            "index_count": self.index_count,
            "mismatch_count": self.mismatch_count,
            "clean": self.clean,
            "missing_count": self.missing_count,
            "extra_count": self.extra_count,
            "stale_count": self.stale_count,
            "acl_mismatched_count": self.acl_mismatched_count,
            "version_mismatched_count": self.version_mismatched_count,
            "missing": list(self.missing),
            "extra": list(self.extra),
            "stale": list(self.stale),
            "acl_mismatched": list(self.acl_mismatched),
            "version_mismatched": list(self.version_mismatched),
        }


class SearchReconciler:
    """Compare canonical source state with a provider index snapshot."""

    async def reconcile(
        self,
        session: AsyncSession,
        *,
        tenant_id: str | None,
        provider: Any,
        index_documents: Iterable[dict[str, Any]] | None = None,
        source_provider: str | None = None,
        sample_limit: int = 100,
        index: str | None = None,
    ) -> ReconciliationReport:
        source_documents = {
            document.document_id: document
            async for document in iter_source_documents(
                session,
                tenant_id=tenant_id,
                provider=source_provider or "zendesk",
            )
        }
        if index_documents is None:
            list_documents = getattr(provider, "list_documents", None)
            if list_documents is None:
                raise RuntimeError("search provider does not support reconciliation snapshots")
            index_documents = await list_documents(index=index)

        indexed = {
            _document_id(document): document
            for document in index_documents
            if _document_id(document)
        }
        missing: list[str] = []
        stale: list[str] = []
        acl_mismatched: list[str] = []
        version_mismatched: list[str] = []

        for document_id, source in source_documents.items():
            indexed_document = indexed.get(document_id)
            if indexed_document is None:
                missing.append(document_id)
                continue
            if indexed_document.get("content_version") != source.content_version:
                stale.append(document_id)
            if not _acl_matches(indexed_document, source):
                acl_mismatched.append(document_id)
            if indexed_document.get("schema_version") != SUPPORT_SEARCH_SCHEMA_VERSION:
                version_mismatched.append(document_id)

        extra = [document_id for document_id in indexed if document_id not in source_documents]
        return ReconciliationReport(
            tenant_id=tenant_id or "*",
            source_count=len(source_documents),
            index_count=len(indexed),
            missing_count=len(missing),
            extra_count=len(extra),
            stale_count=len(stale),
            acl_mismatched_count=len(acl_mismatched),
            version_mismatched_count=len(version_mismatched),
            missing=tuple(missing[:sample_limit]),
            extra=tuple(extra[:sample_limit]),
            stale=tuple(stale[:sample_limit]),
            acl_mismatched=tuple(acl_mismatched[:sample_limit]),
            version_mismatched=tuple(version_mismatched[:sample_limit]),
            _sample_limit=sample_limit,
        )


async def source_documents_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
) -> list[SupportSearchDocument]:
    return [
        document
        async for document in iter_source_documents(
            session,
            tenant_id=tenant_id,
            provider=provider,
        )
    ]


def _document_id(document: dict[str, Any]) -> str | None:
    value = document.get("document_id") or document.get("_id")
    return str(value) if value else None


def _acl_matches(indexed: dict[str, Any], source: SupportSearchDocument) -> bool:
    tokens = indexed.get("acl_tokens") or ()
    return (
        indexed.get("tenant_id") == source.tenant_id
        and f"tenant:{source.tenant_id}" in tokens
        and indexed.get("permission_version", "unknown") == source.permission_version
    )


search_reconciler = SearchReconciler()
