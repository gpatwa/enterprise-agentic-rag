# services/api/app/support_integrations/nango.py
from __future__ import annotations

from typing import Any, Optional

import httpx

from app.config import settings


class NangoNotConfiguredError(RuntimeError):
    pass


class NangoConnectionNotFoundError(RuntimeError):
    pass


class NangoClient:
    """Small REST wrapper over Nango connection and proxy APIs."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        secret_key: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.NANGO_BASE_URL).rstrip("/")
        self.secret_key = secret_key or settings.NANGO_SECRET_KEY
        self.timeout_seconds = timeout_seconds or settings.SUPPORT_CONNECTOR_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(self.secret_key)

    def _headers(self) -> dict[str, str]:
        if not self.secret_key:
            raise NangoNotConfiguredError("NANGO_SECRET_KEY is not configured")
        return {"Authorization": f"Bearer {self.secret_key}"}

    async def get_connection(
        self,
        *,
        connection_id: str,
        provider_config_key: str,
    ) -> dict[str, Any]:
        params = {"connectionId": connection_id}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.get(
                f"{self.base_url}/connections",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        connections = data.get("connections", [])
        for connection in connections:
            if connection.get("provider_config_key") == provider_config_key:
                return connection
        raise NangoConnectionNotFoundError(
            f"Nango connection '{connection_id}' not found for provider config '{provider_config_key}'"
        )

    async def proxy_get(
        self,
        *,
        connection_id: str,
        provider_config_key: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        base_url_override: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            **self._headers(),
            "Connection-Id": connection_id,
            "Provider-Config-Key": provider_config_key,
        }
        if base_url_override:
            headers["Base-Url-Override"] = base_url_override

        normalized = path.lstrip("/")
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.get(
                f"{self.base_url}/proxy/{normalized}",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
