# services/api/app/support/sync.py
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.support.models import SupportSyncRun
from app.support.normalizers import (
    SupportNormalizerError,
    normalize_article,
    normalize_comment,
    normalize_ticket,
)
from app.support.store import support_data_store
from app.support_integrations.manager import (
    SupportIntegrationError,
    support_integration_manager,
)

logger = logging.getLogger(__name__)


class SupportSyncError(RuntimeError):
    pass


class SupportSyncRunner:
    async def sync_provider(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
        requested_by: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        provider = provider.lower().strip()
        cursor_started_at = await support_data_store.latest_success_cursor(
            session, tenant_id=tenant_id, provider=provider
        )
        run = SupportSyncRun(
            tenant_id=tenant_id,
            provider=provider,
            status="running",
            cursor_started_at=cursor_started_at,
            metadata_={"limit": limit},
            created_by=requested_by,
            started_at=datetime.utcnow(),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        records_seen = 0
        records_upserted = 0
        records_skipped = 0
        comments_seen = 0
        comments_upserted = 0
        articles_seen = 0
        articles_upserted = 0
        cursor_finished_at = cursor_started_at

        try:
            previews = await support_integration_manager.list_ticket_previews(
                session,
                tenant_id=tenant_id,
                provider=provider,
                limit=min(max(limit, 1), 200),
            )
            for preview in previews:
                records_seen += 1
                try:
                    normalized = normalize_ticket(provider, preview.raw)
                except SupportNormalizerError as e:
                    records_skipped += 1
                    logger.warning("support ticket normalize failed provider=%s: %s", provider, e)
                    continue

                if normalized.customer:
                    await support_data_store.upsert_customer(
                        session,
                        tenant_id=tenant_id,
                        customer=normalized.customer,
                    )
                await support_data_store.upsert_ticket(
                    session,
                    tenant_id=tenant_id,
                    ticket=normalized,
                )
                records_upserted += 1
                comment_counts = await self._sync_ticket_comments(
                    session,
                    tenant_id=tenant_id,
                    provider=provider,
                    ticket_id=normalized.external_id,
                )
                comments_seen += comment_counts["seen"]
                comments_upserted += comment_counts["upserted"]
                records_skipped += comment_counts["skipped"]
                cursor_finished_at = self._max_cursor(
                    cursor_finished_at,
                    self._dt_to_cursor(normalized.updated_at_external),
                )

            article_counts = await self._sync_articles(
                session,
                tenant_id=tenant_id,
                provider=provider,
                limit=min(max(limit, 1), 100),
            )
            articles_seen += article_counts["seen"]
            articles_upserted += article_counts["upserted"]
            records_skipped += article_counts["skipped"]

            run.status = "succeeded"
            run.records_seen = records_seen
            run.records_upserted = records_upserted
            run.records_skipped = records_skipped
            run.metadata_ = {
                **(run.metadata_ or {}),
                "comments_seen": comments_seen,
                "comments_upserted": comments_upserted,
                "articles_seen": articles_seen,
                "articles_upserted": articles_upserted,
            }
            run.cursor_finished_at = cursor_finished_at
            run.finished_at = datetime.utcnow()
            await session.commit()
            await session.refresh(run)
            return self._run_to_dict(run)

        except SupportIntegrationError as e:
            await self._mark_failed(session, run, str(e), records_seen, records_upserted, records_skipped)
            raise SupportSyncError(str(e)) from e
        except Exception as e:
            message = str(e)[:500] or e.__class__.__name__
            await self._mark_failed(session, run, message, records_seen, records_upserted, records_skipped)
            raise SupportSyncError(message) from e

    async def _sync_ticket_comments(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
        ticket_id: str,
    ) -> dict[str, int]:
        counts = {"seen": 0, "upserted": 0, "skipped": 0}
        try:
            comments = await support_integration_manager.list_ticket_comments(
                session,
                tenant_id=tenant_id,
                provider=provider,
                ticket_id=ticket_id,
                limit=100,
            )
        except Exception as e:
            counts["skipped"] += 1
            logger.warning(
                "support comments sync failed provider=%s ticket=%s: %s",
                provider,
                ticket_id,
                e,
            )
            return counts

        for preview in comments:
            counts["seen"] += 1
            try:
                normalized = normalize_comment(
                    provider,
                    preview.raw,
                    ticket_external_id=ticket_id,
                )
            except SupportNormalizerError as e:
                counts["skipped"] += 1
                logger.warning(
                    "support comment normalize failed provider=%s ticket=%s: %s",
                    provider,
                    ticket_id,
                    e,
                )
                continue

            await support_data_store.upsert_comment(
                session,
                tenant_id=tenant_id,
                comment=normalized,
            )
            counts["upserted"] += 1
        return counts

    async def _sync_articles(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
        limit: int,
    ) -> dict[str, int]:
        counts = {"seen": 0, "upserted": 0, "skipped": 0}
        try:
            articles = await support_integration_manager.list_article_previews(
                session,
                tenant_id=tenant_id,
                provider=provider,
                limit=limit,
            )
        except Exception as e:
            counts["skipped"] += 1
            logger.warning("support article sync failed provider=%s: %s", provider, e)
            return counts

        for preview in articles:
            counts["seen"] += 1
            try:
                normalized = normalize_article(provider, preview.raw)
            except SupportNormalizerError as e:
                counts["skipped"] += 1
                logger.warning("support article normalize failed provider=%s: %s", provider, e)
                continue

            await support_data_store.upsert_article(
                session,
                tenant_id=tenant_id,
                article=normalized,
            )
            counts["upserted"] += 1
        return counts

    async def _mark_failed(
        self,
        session: AsyncSession,
        run: SupportSyncRun,
        message: str,
        records_seen: int,
        records_upserted: int,
        records_skipped: int,
    ) -> None:
        run.status = "failed"
        run.records_seen = records_seen
        run.records_upserted = records_upserted
        run.records_skipped = records_skipped
        run.error_message = message
        run.finished_at = datetime.utcnow()
        await session.commit()
        await session.refresh(run)

    def _run_to_dict(self, run: SupportSyncRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "tenant_id": run.tenant_id,
            "provider": run.provider,
            "status": run.status,
            "cursor_started_at": run.cursor_started_at,
            "cursor_finished_at": run.cursor_finished_at,
            "records_seen": run.records_seen,
            "records_upserted": run.records_upserted,
            "records_skipped": run.records_skipped,
            "error_message": run.error_message,
            "metadata": run.metadata_ or {},
            "started_at": self._dt_to_cursor(run.started_at),
            "finished_at": self._dt_to_cursor(run.finished_at),
            "created_by": run.created_by,
        }

    def _dt_to_cursor(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.replace(microsecond=0).isoformat() + "Z"

    def _max_cursor(self, current: str | None, candidate: str | None) -> str | None:
        if candidate is None:
            return current
        if current is None:
            return candidate
        return max(current, candidate)


support_sync_runner = SupportSyncRunner()
