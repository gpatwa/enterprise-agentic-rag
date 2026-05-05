# services/api/app/routes/context.py
"""
Admin API for Context Layers.

CRUD endpoints for managing:
- Annotations & glossary terms (Layer 2)
- Business rules & terminology (Layer 4)
- Code & pipeline context (Layer 3)
- Document metadata (Layer 1, read-only)

All endpoints are tenant-scoped via TenantContext.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.tenant import TenantContext, get_tenant_context
from app.context.manager import ContextManager

router = APIRouter()
logger = logging.getLogger(__name__)

# Singleton manager
_manager = ContextManager()


# ── Schemas ──────────────────────────────────────────────────────

class AnnotationCreate(BaseModel):
    annotation_type: str = Field(..., description="glossary | kpi | description | note")
    key: str = Field(..., min_length=1, description="Term or identifier")
    value: str = Field(..., min_length=1, description="Definition or description")


class AnnotationUpdate(BaseModel):
    annotation_type: Optional[str] = None
    key: Optional[str] = None
    value: Optional[str] = None


class BusinessRuleCreate(BaseModel):
    context_type: str = Field(..., description="terminology | business_rule | role_context | org_structure")
    key: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)
    applies_to_roles: List[str] = Field(default=["all"])
    priority: int = Field(default=0)


class BusinessRuleUpdate(BaseModel):
    context_type: Optional[str] = None
    key: Optional[str] = None
    value: Optional[str] = None
    applies_to_roles: Optional[List[str]] = None
    priority: Optional[int] = None


class CodeContextCreate(BaseModel):
    context_type: str = Field(..., description="etl_pipeline | sql_query | api_endpoint | data_lineage")
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    source_code: str = Field(default="")
    lineage: dict = Field(default_factory=dict)


class CodeContextUpdate(BaseModel):
    context_type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    source_code: Optional[str] = None
    lineage: Optional[dict] = None


# ── Annotations (Layer 2) ───────────────────────────────────────

@router.post("/annotations", status_code=201)
async def create_annotation(
    body: AnnotationCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    result = await _manager.create_annotation(
        tenant_id=ctx.tenant_id,
        annotation_type=body.annotation_type,
        key=body.key,
        value=body.value,
        created_by=ctx.user_id,
    )
    logger.info(f"Created annotation '{body.key}' (tenant={ctx.tenant_id})")
    return result


@router.get("/annotations")
async def list_annotations(
    annotation_type: Optional[str] = None,
    limit: int = 50,
    ctx: TenantContext = Depends(get_tenant_context),
):
    return await _manager.list_annotations(ctx.tenant_id, annotation_type, limit)


@router.get("/annotations/{annotation_id}")
async def get_annotation(
    annotation_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
):
    result = await _manager.get_annotation(ctx.tenant_id, annotation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return result


@router.put("/annotations/{annotation_id}")
async def update_annotation(
    annotation_id: int,
    body: AnnotationUpdate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    result = await _manager.update_annotation(ctx.tenant_id, annotation_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return result


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(
    annotation_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
):
    deleted = await _manager.delete_annotation(ctx.tenant_id, annotation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"deleted": True}


# ── Business Rules (Layer 4) ────────────────────────────────────

@router.post("/business-rules", status_code=201)
async def create_business_rule(
    body: BusinessRuleCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    result = await _manager.create_business_rule(
        tenant_id=ctx.tenant_id,
        context_type=body.context_type,
        key=body.key,
        value=body.value,
        applies_to_roles=body.applies_to_roles,
        priority=body.priority,
    )
    logger.info(f"Created business rule '{body.key}' (tenant={ctx.tenant_id})")
    return result


@router.get("/business-rules")
async def list_business_rules(
    context_type: Optional[str] = None,
    limit: int = 50,
    ctx: TenantContext = Depends(get_tenant_context),
):
    return await _manager.list_business_rules(ctx.tenant_id, context_type, limit)


@router.get("/business-rules/{rule_id}")
async def get_business_rule(
    rule_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
):
    result = await _manager.get_business_rule(ctx.tenant_id, rule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Business rule not found")
    return result


@router.put("/business-rules/{rule_id}")
async def update_business_rule(
    rule_id: int,
    body: BusinessRuleUpdate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    result = await _manager.update_business_rule(ctx.tenant_id, rule_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Business rule not found")
    return result


@router.delete("/business-rules/{rule_id}")
async def delete_business_rule(
    rule_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
):
    deleted = await _manager.delete_business_rule(ctx.tenant_id, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Business rule not found")
    return {"deleted": True}


# ── Code Context (Layer 3) ──────────────────────────────────────

@router.post("/code-context", status_code=201)
async def create_code_context(
    body: CodeContextCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    result = await _manager.create_code_context(
        tenant_id=ctx.tenant_id,
        context_type=body.context_type,
        name=body.name,
        description=body.description,
        source_code=body.source_code,
        lineage=body.lineage,
    )
    logger.info(f"Created code context '{body.name}' (tenant={ctx.tenant_id})")
    return result


@router.get("/code-context")
async def list_code_contexts(
    context_type: Optional[str] = None,
    limit: int = 50,
    ctx: TenantContext = Depends(get_tenant_context),
):
    return await _manager.list_code_contexts(ctx.tenant_id, context_type, limit)


@router.get("/code-context/{context_id}")
async def get_code_context(
    context_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
):
    result = await _manager.get_code_context(ctx.tenant_id, context_id)
    if not result:
        raise HTTPException(status_code=404, detail="Code context not found")
    return result


@router.put("/code-context/{context_id}")
async def update_code_context(
    context_id: int,
    body: CodeContextUpdate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    result = await _manager.update_code_context(ctx.tenant_id, context_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Code context not found")
    return result


@router.delete("/code-context/{context_id}")
async def delete_code_context(
    context_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
):
    deleted = await _manager.delete_code_context(ctx.tenant_id, context_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Code context not found")
    return {"deleted": True}


# ── Document Metadata (Layer 1, read-only) ──────────────────────

@router.get("/metadata")
async def list_document_metadata(
    limit: int = 50,
    ctx: TenantContext = Depends(get_tenant_context),
):
    return await _manager.list_document_metadata(ctx.tenant_id, limit)


@router.get("/metadata/{document_id}")
async def get_document_metadata(
    document_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    result = await _manager.get_document_metadata(ctx.tenant_id, document_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document metadata not found")
    return result
