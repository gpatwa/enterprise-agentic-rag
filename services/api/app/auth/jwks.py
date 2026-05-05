# services/api/app/auth/jwks.py
"""
JWKS (JSON Web Key Set) fetcher for RS256 token validation.

When AUTH_PROVIDER is set to "auth0", "azure_ad", or "cognito",
the app validates JWTs using public keys from the IdP's JWKS endpoint
instead of the local symmetric JWT_SECRET_KEY.

The JWKS is fetched once and cached (with periodic refresh) to avoid
hitting the IdP on every request.
"""
import logging
import time
from typing import Optional

import httpx
from jose import JWTError
from jose import jwt as jose_jwt

logger = logging.getLogger(__name__)

# Cache TTL in seconds (refresh JWKS every 6 hours)
JWKS_CACHE_TTL = 6 * 3600


class JWKSFetcher:
    """
    Fetches and caches the JWKS from an IdP's well-known endpoint.

    Usage:
        fetcher = JWKSFetcher("https://your-tenant.auth0.com/.well-known/jwks.json")
        await fetcher.refresh()
        payload = fetcher.decode_token(token, audience="...", issuer="...")
    """

    def __init__(self, jwks_url: str):
        self._jwks_url = jwks_url
        self._keys: list[dict] = []
        self._last_fetched: float = 0

    async def refresh(self, force: bool = False) -> None:
        """
        Fetch the JWKS from the IdP. Skips if cache is fresh.

        Args:
            force: If True, always re-fetch regardless of TTL.
        """
        now = time.time()
        if not force and self._keys and (now - self._last_fetched) < JWKS_CACHE_TTL:
            return  # cache is still fresh

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._jwks_url)
                resp.raise_for_status()
                data = resp.json()
                self._keys = data.get("keys", [])
                self._last_fetched = now
                logger.info(
                    f"JWKS refreshed from {self._jwks_url} "
                    f"({len(self._keys)} keys)"
                )
        except Exception as e:
            logger.error(f"Failed to fetch JWKS from {self._jwks_url}: {e}")
            if not self._keys:
                raise  # no cached keys available, can't proceed

    def _get_signing_key(self, kid: str) -> Optional[dict]:
        """Find the key matching the JWT header's 'kid'."""
        for key in self._keys:
            if key.get("kid") == kid:
                return key
        return None

    def decode_token(
        self,
        token: str,
        audience: Optional[str] = None,
        issuer: Optional[str] = None,
    ) -> dict:
        """
        Decode and verify an RS256 JWT using the cached JWKS.

        Args:
            token: The raw JWT string.
            audience: Expected 'aud' claim (optional).
            issuer: Expected 'iss' claim (optional).

        Returns:
            The decoded token payload dict.

        Raises:
            JWTError: If verification fails.
            ValueError: If no matching key is found.
        """
        # Get the kid from the token header
        try:
            unverified_header = jose_jwt.get_unverified_header(token)
        except JWTError:
            raise ValueError("Unable to parse JWT header")

        kid = unverified_header.get("kid")
        if not kid:
            raise ValueError("JWT header missing 'kid' claim")

        signing_key = self._get_signing_key(kid)
        if not signing_key:
            raise ValueError(
                f"No matching JWKS key found for kid={kid}. "
                f"Available: {[k.get('kid') for k in self._keys]}"
            )

        # Build decode kwargs (audience + issuer are added below if provided)
        kwargs: dict = {
            "algorithms": ["RS256"],
        }
        if audience:
            kwargs["audience"] = audience
        if issuer:
            kwargs["issuer"] = issuer

        return jose_jwt.decode(
            token,
            signing_key,
            **kwargs,
        )


# Global instance — initialised during app startup if AUTH_PROVIDER != "local"
_jwks_fetcher: Optional[JWKSFetcher] = None


def get_jwks_fetcher() -> Optional[JWKSFetcher]:
    """Return the global JWKS fetcher (None if using local HS256 auth)."""
    return _jwks_fetcher


async def init_jwks_fetcher(jwks_url: str) -> JWKSFetcher:
    """
    Create and initialise the global JWKS fetcher.
    Called once during app startup.
    """
    global _jwks_fetcher
    _jwks_fetcher = JWKSFetcher(jwks_url)
    await _jwks_fetcher.refresh()
    return _jwks_fetcher
