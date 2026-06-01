# services/api/app/support_integrations/catalog.py
from __future__ import annotations

from app.config import settings
from app.support_integrations.types import SupportCatalogEntry


class SupportIntegrationCatalog:
    """Static first-wave connector catalog for support resolution workflows."""

    @classmethod
    def all(cls) -> tuple[SupportCatalogEntry, ...]:
        return (
            SupportCatalogEntry(
                provider="zendesk",
                display_name="Zendesk",
                description=(
                    "Sync tickets, comments, tags, requester context, and help center "
                    "signals for resolution assistance and repeat-issue analytics."
                ),
                category="ticketing",
                auth_modes=("nango", "direct_env"),
                nango_provider_config_key=settings.NANGO_PROVIDER_CONFIG_KEY_ZENDESK,
                direct_env_vars=("ZENDESK_SUBDOMAIN", "ZENDESK_EMAIL", "ZENDESK_API_TOKEN"),
                objects=("tickets", "users", "organizations", "articles"),
                docs_url="https://developer.zendesk.com/api-reference/ticketing/introduction/",
            ),
            SupportCatalogEntry(
                provider="intercom",
                display_name="Intercom",
                description=(
                    "Sync conversations and customer context so agents can find "
                    "similar resolved issues and draft cited replies."
                ),
                category="ticketing",
                auth_modes=("nango", "direct_env"),
                nango_provider_config_key=settings.NANGO_PROVIDER_CONFIG_KEY_INTERCOM,
                direct_env_vars=("INTERCOM_ACCESS_TOKEN",),
                objects=("conversations", "contacts", "teams", "admins"),
                docs_url="https://developers.intercom.com/docs/references/rest-api/api.intercom.io/",
            ),
        )

    @classmethod
    def get(cls, provider: str) -> SupportCatalogEntry | None:
        provider = provider.lower().strip()
        return next((entry for entry in cls.all() if entry.provider == provider), None)

    @classmethod
    def names(cls) -> set[str]:
        return {entry.provider for entry in cls.all()}
