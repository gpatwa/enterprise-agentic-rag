# services/api/app/context/manager.py
"""
CRUD operations for context layers.

Handles create/read/update/delete for:
- Annotations (Layer 2)
- Business Rules (Layer 4)
- Code Context (Layer 3)
- Document Metadata (Layer 1, read-only)
"""
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import and_, delete, select

import app.memory.postgres as _pg
from app.config import settings
from app.context.models import Annotation, BusinessContext, CodeContext, DocumentMetadata

logger = logging.getLogger(__name__)

_single_tenant = settings.SINGLE_TENANT_MODE


class ContextManager:
    """CRUD operations for all context layer tables."""

    # ── Annotations (Layer 2) ──────────────────────────────────────

    async def create_annotation(
        self,
        tenant_id: str,
        annotation_type: str,
        key: str,
        value: str,
        created_by: str = "",
    ) -> dict:
        async with _pg.AsyncSessionLocal() as session:
            async with session.begin():
                ann = Annotation(
                    tenant_id=tenant_id,
                    annotation_type=annotation_type,
                    key=key,
                    value=value,
                    created_by=created_by,
                )
                session.add(ann)
            await session.refresh(ann)
            return _to_dict(ann)

    async def list_annotations(
        self,
        tenant_id: str,
        annotation_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        async with _pg.AsyncSessionLocal() as session:
            conditions = []
            if not _single_tenant:
                conditions.append(Annotation.tenant_id == tenant_id)
            if annotation_type:
                conditions.append(Annotation.annotation_type == annotation_type)

            query = select(Annotation)
            if conditions:
                query = query.where(and_(*conditions))
            query = query.order_by(Annotation.created_at.desc()).limit(limit)

            result = await session.execute(query)
            return [_to_dict(a) for a in result.scalars().all()]

    async def get_annotation(self, tenant_id: str, annotation_id: int) -> Optional[dict]:
        async with _pg.AsyncSessionLocal() as session:
            ann = await _get_by_id(session, Annotation, annotation_id, tenant_id)
            return _to_dict(ann) if ann else None

    async def update_annotation(
        self, tenant_id: str, annotation_id: int, **kwargs
    ) -> Optional[dict]:
        async with _pg.AsyncSessionLocal() as session:
            async with session.begin():
                ann = await _get_by_id(session, Annotation, annotation_id, tenant_id)
                if not ann:
                    return None
                for k, v in kwargs.items():
                    if hasattr(ann, k) and k not in ("id", "tenant_id", "created_at"):
                        setattr(ann, k, v)
                ann.updated_at = datetime.utcnow()
            await session.refresh(ann)
            return _to_dict(ann)

    async def delete_annotation(self, tenant_id: str, annotation_id: int) -> bool:
        return await _delete_by_id(Annotation, annotation_id, tenant_id)

    # ── Business Context (Layer 4) ─────────────────────────────────

    async def create_business_rule(
        self,
        tenant_id: str,
        context_type: str,
        key: str,
        value: str,
        applies_to_roles: Optional[List[str]] = None,
        priority: int = 0,
    ) -> dict:
        async with _pg.AsyncSessionLocal() as session:
            async with session.begin():
                rule = BusinessContext(
                    tenant_id=tenant_id,
                    context_type=context_type,
                    key=key,
                    value=value,
                    applies_to_roles=applies_to_roles or ["all"],
                    priority=priority,
                )
                session.add(rule)
            await session.refresh(rule)
            return _to_dict(rule)

    async def list_business_rules(
        self,
        tenant_id: str,
        context_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        async with _pg.AsyncSessionLocal() as session:
            conditions = []
            if not _single_tenant:
                conditions.append(BusinessContext.tenant_id == tenant_id)
            if context_type:
                conditions.append(BusinessContext.context_type == context_type)

            query = select(BusinessContext)
            if conditions:
                query = query.where(and_(*conditions))
            query = query.order_by(BusinessContext.priority.desc()).limit(limit)

            result = await session.execute(query)
            return [_to_dict(r) for r in result.scalars().all()]

    async def get_business_rule(self, tenant_id: str, rule_id: int) -> Optional[dict]:
        async with _pg.AsyncSessionLocal() as session:
            rule = await _get_by_id(session, BusinessContext, rule_id, tenant_id)
            return _to_dict(rule) if rule else None

    async def update_business_rule(
        self, tenant_id: str, rule_id: int, **kwargs
    ) -> Optional[dict]:
        async with _pg.AsyncSessionLocal() as session:
            async with session.begin():
                rule = await _get_by_id(session, BusinessContext, rule_id, tenant_id)
                if not rule:
                    return None
                for k, v in kwargs.items():
                    if hasattr(rule, k) and k not in ("id", "tenant_id", "created_at"):
                        setattr(rule, k, v)
                rule.updated_at = datetime.utcnow()
            await session.refresh(rule)
            return _to_dict(rule)

    async def delete_business_rule(self, tenant_id: str, rule_id: int) -> bool:
        return await _delete_by_id(BusinessContext, rule_id, tenant_id)

    # ── Code Context (Layer 3) ─────────────────────────────────────

    async def create_code_context(
        self,
        tenant_id: str,
        context_type: str,
        name: str,
        description: str = "",
        source_code: str = "",
        lineage: Optional[dict] = None,
    ) -> dict:
        async with _pg.AsyncSessionLocal() as session:
            async with session.begin():
                ctx = CodeContext(
                    tenant_id=tenant_id,
                    context_type=context_type,
                    name=name,
                    description=description,
                    source_code=source_code,
                    lineage=lineage or {},
                )
                session.add(ctx)
            await session.refresh(ctx)
            return _to_dict(ctx)

    async def list_code_contexts(
        self,
        tenant_id: str,
        context_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        async with _pg.AsyncSessionLocal() as session:
            conditions = []
            if not _single_tenant:
                conditions.append(CodeContext.tenant_id == tenant_id)
            if context_type:
                conditions.append(CodeContext.context_type == context_type)

            query = select(CodeContext)
            if conditions:
                query = query.where(and_(*conditions))
            query = query.order_by(CodeContext.created_at.desc()).limit(limit)

            result = await session.execute(query)
            return [_to_dict(c) for c in result.scalars().all()]

    async def get_code_context(self, tenant_id: str, context_id: int) -> Optional[dict]:
        async with _pg.AsyncSessionLocal() as session:
            ctx = await _get_by_id(session, CodeContext, context_id, tenant_id)
            return _to_dict(ctx) if ctx else None

    async def update_code_context(
        self, tenant_id: str, context_id: int, **kwargs
    ) -> Optional[dict]:
        async with _pg.AsyncSessionLocal() as session:
            async with session.begin():
                ctx = await _get_by_id(session, CodeContext, context_id, tenant_id)
                if not ctx:
                    return None
                for k, v in kwargs.items():
                    if hasattr(ctx, k) and k not in ("id", "tenant_id", "created_at"):
                        setattr(ctx, k, v)
                ctx.updated_at = datetime.utcnow()
            await session.refresh(ctx)
            return _to_dict(ctx)

    async def delete_code_context(self, tenant_id: str, context_id: int) -> bool:
        return await _delete_by_id(CodeContext, context_id, tenant_id)

    # ── Document Metadata (Layer 1, read-only) ─────────────────────

    async def list_document_metadata(
        self, tenant_id: str, limit: int = 50
    ) -> List[dict]:
        async with _pg.AsyncSessionLocal() as session:
            conditions = []
            if not _single_tenant:
                conditions.append(DocumentMetadata.tenant_id == tenant_id)

            query = select(DocumentMetadata)
            if conditions:
                query = query.where(and_(*conditions))
            query = query.order_by(DocumentMetadata.ingested_at.desc()).limit(limit)

            result = await session.execute(query)
            return [_to_dict(d) for d in result.scalars().all()]

    async def get_document_metadata(
        self, tenant_id: str, document_id: str
    ) -> Optional[dict]:
        async with _pg.AsyncSessionLocal() as session:
            conditions = [DocumentMetadata.document_id == document_id]
            if not _single_tenant:
                conditions.append(DocumentMetadata.tenant_id == tenant_id)

            result = await session.execute(
                select(DocumentMetadata).where(and_(*conditions))
            )
            doc = result.scalars().first()
            return _to_dict(doc) if doc else None


# ── Helpers ────────────────────────────────────────────────────────

async def _get_by_id(session, model, record_id: int, tenant_id: str):
    """Get a record by ID, scoped to tenant."""
    conditions = [model.id == record_id]
    if not _single_tenant:
        conditions.append(model.tenant_id == tenant_id)
    result = await session.execute(select(model).where(and_(*conditions)))
    return result.scalars().first()


async def _delete_by_id(model, record_id: int, tenant_id: str) -> bool:
    """Delete a record by ID, scoped to tenant."""
    async with _pg.AsyncSessionLocal() as session:
        async with session.begin():
            conditions = [model.id == record_id]
            if not _single_tenant:
                conditions.append(model.tenant_id == tenant_id)
            result = await session.execute(
                delete(model).where(and_(*conditions))
            )
            return result.rowcount > 0


def _to_dict(obj) -> dict:
    """Convert a SQLAlchemy model instance to a dict."""
    if obj is None:
        return {}
    d = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d
