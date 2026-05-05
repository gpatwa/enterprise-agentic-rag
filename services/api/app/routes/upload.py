# services/api/app/routes/upload.py
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.tenant import TenantContext, get_tenant_context
from app.clients.storage.factory import create_storage_client
from app.config import settings

router = APIRouter()

# Initialize cloud storage client via provider factory
# Works with S3 (AWS/MinIO) or Azure Blob — selected via STORAGE_PROVIDER env var
storage_client = create_storage_client(settings.STORAGE_PROVIDER)


class PresignedURLRequest(BaseModel):
    filename: str
    content_type: str  # e.g., "application/pdf"


class PresignedURLResponse(BaseModel):
    upload_url: str
    file_id: str
    object_key: str


@router.post("/generate-presigned-url", response_model=PresignedURLResponse)
async def generate_upload_url(
    req: PresignedURLRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Generates a secure, temporary URL for the frontend to upload a file
    directly to cloud storage (S3 or Azure Blob).

    Use case: Handling 1GB+ PDF/Video files without blocking the API server.

    Object keys are namespaced by tenant_id to enforce storage isolation:
        uploads/{tenant_id}/{user_id}/{file_id}.{ext}
    """
    # 1. Generate a unique file ID (UUID) to prevent overwrites
    file_id = str(uuid.uuid4())
    extension = req.filename.split(".")[-1] if "." in req.filename else "bin"

    # Namespace by tenant_id + user_id for isolation
    object_key = f"uploads/{ctx.tenant_id}/{ctx.user_id}/{file_id}.{extension}"

    try:
        # 2. Generate the Presigned URL via the abstracted StorageClient
        url = storage_client.generate_presigned_upload_url(
            key=object_key,
            content_type=req.content_type,
            metadata={
                "original_filename": req.filename,
                "user_id": ctx.user_id,
                "tenant_id": ctx.tenant_id,
            },
            expires_in=3600,  # URL valid for 1 hour
        )

        return PresignedURLResponse(
            upload_url=url,
            file_id=file_id,
            object_key=object_key,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
