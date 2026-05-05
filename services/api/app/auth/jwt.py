# services/api/app/auth/jwt.py
import logging
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

# OAuth2 scheme tells Swagger UI where to send the token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# Default tenant for tokens minted before multi-tenancy
DEFAULT_TENANT_ID = "default"


DEFAULT_ACCESS_TTL = 3600           # 1 hour
DEFAULT_REFRESH_TTL = 14 * 86400    # 14 days


def create_token(
    user_id: str = "dev-user",
    role: str = "admin",
    tenant_id: str = DEFAULT_TENANT_ID,
    permissions: list = None,
    expires_in: int = DEFAULT_ACCESS_TTL,
) -> str:
    """
    Creates a signed JWT token using the local HS256 secret.
    Used by the /auth/token endpoint and the CLI helper.

    Note: When AUTH_PROVIDER is set to an external IdP (Auth0, Azure AD,
    Cognito), tokens are minted by the IdP — this function is only used
    for local dev and testing.

    The token now carries a 'tenant_id' claim for multi-tenant isolation.
    """
    payload = {
        "sub": user_id,
        "role": role,
        "tenant_id": tenant_id,
        "permissions": permissions or ["read", "write"],
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def create_refresh_token(
    user_id: str,
    role: str,
    tenant_id: str,
    expires_in: int = DEFAULT_REFRESH_TTL,
) -> str:
    """
    Long-lived refresh token. Carries a 'type=refresh' claim so it can't be
    used as an access token by mistake.
    """
    payload = {
        "sub": user_id,
        "role": role,
        "tenant_id": tenant_id,
        "type": "refresh",
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def verify_refresh_token(token: str) -> dict:
    """
    Decode + validate a refresh token. Raises HTTPException(401) on any
    failure: bad signature, expiry, or wrong token type.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    return payload


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Validates the JWT Token from the Authorization header.
    Decodes user info (ID, Role, Permissions, Tenant).

    Supports two auth modes:
      - LOCAL (HS256): Token is verified with the local JWT_SECRET_KEY.
      - EXTERNAL (RS256): Token is verified via JWKS from an IdP
        (Auth0 / Azure AD / Cognito). Requires JWT_JWKS_URL to be set.

    Backward compatible: tokens without 'tenant_id' default to "default".
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        if settings.AUTH_PROVIDER != "local" and settings.JWT_JWKS_URL:
            # ===================== RS256 / JWKS (External IdP) =====================
            from app.auth.jwks import get_jwks_fetcher

            fetcher = get_jwks_fetcher()
            if not fetcher:
                logger.error("JWKS fetcher not initialised but AUTH_PROVIDER != local")
                raise credentials_exception

            # Refresh JWKS if stale (uses TTL cache internally)
            await fetcher.refresh()

            payload = fetcher.decode_token(
                token,
                audience=settings.JWT_AUDIENCE,
                issuer=settings.JWT_ISSUER,
            )
        else:
            # ===================== HS256 (Local Secret) =====================
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=["HS256"],
            )

        user_id: str = payload.get("sub")
        role: str = payload.get("role", "user")
        tenant_id: str = payload.get("tenant_id", DEFAULT_TENANT_ID)

        if user_id is None:
            raise credentials_exception

        # Check Expiration (Redundant if jwt.decode does it, but good for safety)
        exp = payload.get("exp")
        if exp and time.time() > exp:
            raise HTTPException(status_code=401, detail="Token expired")

        # Return user context dict (now includes tenant_id)
        return {
            "id": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "permissions": payload.get("permissions", []),
        }

    except (JWTError, ValueError) as e:
        logger.debug(f"Token validation failed: {e}")
        raise credentials_exception
