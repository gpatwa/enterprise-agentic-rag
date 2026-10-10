"""Customer-managed secret lease boundary with redacted operational output."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class SecretProvider(Protocol):
    def read(self, tenant_id: str, secret_name: str) -> str:
        ...


@dataclass(frozen=True)
class SecretLease:
    tenant_id: str
    secret_name: str
    version: str
    expires_at: datetime


class InMemorySecretProvider:
    """Test/demonstration provider; production uses a customer vault adapter."""

    def __init__(self, secrets: dict[tuple[str, str], tuple[str, str]]):
        self._secrets = secrets

    def read(self, tenant_id: str, secret_name: str) -> str:
        try:
            return self._secrets[(tenant_id, secret_name)][0]
        except KeyError as exc:
            raise KeyError("secret was not found") from exc

    def lease(self, tenant_id: str, secret_name: str, version: str, expires_at: datetime) -> SecretLease:
        if (tenant_id, secret_name) not in self._secrets or self._secrets[(tenant_id, secret_name)][1] != version:
            raise KeyError("secret version was not found")
        if expires_at <= datetime.now(timezone.utc):
            raise ValueError("secret lease must be in the future")
        return SecretLease(tenant_id, secret_name, version, expires_at)


def redact_secret(value: str) -> str:
    return "[REDACTED]" if value else value
