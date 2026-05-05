# services/api/app/routes/auth.py
"""
Token endpoints.

POST /auth/token   — dev-only token mint (ENV=dev). Returns access + refresh.
POST /auth/refresh — exchange a refresh token for a new access token.

In production, /auth/token is disabled; access tokens are minted by the IdP
(Cognito / Auth0 / Azure AD) and verified via JWKS by `get_current_user`.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.auth.jwt import (
    DEFAULT_ACCESS_TTL,
    DEFAULT_REFRESH_TTL,
    DEFAULT_TENANT_ID,
    create_refresh_token,
    create_token,
    verify_refresh_token,
)

router = APIRouter()


class TokenRequest(BaseModel):
    user_id: str = Field(default="dev-user")
    role: str = Field(default="admin")
    tenant_id: str = Field(default=DEFAULT_TENANT_ID)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    tenant_id: str
    expires_in: int
    refresh_expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/token", response_model=TokenResponse)
async def issue_dev_token(req: TokenRequest = TokenRequest()):
    """
    Dev-only mint. ENV=prod returns 403. Returns short-lived access (1h) +
    long-lived refresh (14d) — clients refresh with /auth/refresh.
    """
    if settings.ENV not in ("dev", "test"):
        raise HTTPException(status_code=403, detail="Dev token endpoint disabled")
    access = create_token(
        user_id=req.user_id,
        role=req.role,
        tenant_id=req.tenant_id,
        expires_in=DEFAULT_ACCESS_TTL,
    )
    refresh = create_refresh_token(
        user_id=req.user_id, role=req.role, tenant_id=req.tenant_id
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user_id=req.user_id,
        tenant_id=req.tenant_id,
        expires_in=DEFAULT_ACCESS_TTL,
        refresh_expires_in=DEFAULT_REFRESH_TTL,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(req: RefreshRequest):
    """
    Exchange a refresh token for a new access token (and a rotated refresh).
    Refresh-token rotation prevents long-term token replay.
    """
    payload = verify_refresh_token(req.refresh_token)
    user_id = payload.get("sub")
    role = payload.get("role", "user")
    tenant_id = payload.get("tenant_id", DEFAULT_TENANT_ID)

    new_access = create_token(
        user_id=user_id, role=role, tenant_id=tenant_id, expires_in=DEFAULT_ACCESS_TTL
    )
    new_refresh = create_refresh_token(user_id=user_id, role=role, tenant_id=tenant_id)
    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user_id=user_id,
        tenant_id=tenant_id,
        expires_in=DEFAULT_ACCESS_TTL,
        refresh_expires_in=DEFAULT_REFRESH_TTL,
    )
