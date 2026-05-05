# services/api/app/mcp/catalog.py
"""
Static catalog of MCP servers Compass ships support for.

Adding a new Tier-2/Tier-3 server is just appending an MCPCatalogEntry —
the rest of the manager is generic. Catalog is intentionally a class with
classmethod accessors (not a free dict) so we can layer in tenant-aware
filtering / feature flags later without breaking import sites.
"""
from __future__ import annotations

from typing import Optional

from app.mcp.types import MCPCatalogEntry


# Tier-1 servers per the A1 plan. PAT-style first; Drive (OAuth2) lands in Phase 4.
_ENTRIES: dict[str, MCPCatalogEntry] = {
    "slack": MCPCatalogEntry(
        server_name="slack",
        display_name="Slack",
        description=(
            "Search messages, list channels, and post replies in your Slack "
            "workspace. Best for retrieving conversation context and threads."
        ),
        npx_package="@modelcontextprotocol/server-slack",
        required_credentials=("SLACK_BOT_TOKEN", "SLACK_TEAM_ID"),
        docs_url="https://api.slack.com/apps",
    ),
    "github": MCPCatalogEntry(
        server_name="github",
        display_name="GitHub",
        description=(
            "Read repositories, issues, and pull requests. Useful for code "
            "ownership, incident timelines, and engineering context."
        ),
        npx_package="@modelcontextprotocol/server-github",
        required_credentials=("GITHUB_PERSONAL_ACCESS_TOKEN",),
        docs_url="https://github.com/settings/tokens",
    ),
    "notion": MCPCatalogEntry(
        server_name="notion",
        display_name="Notion",
        description=(
            "Search Notion workspaces and read pages. Great for runbooks, "
            "specs, and team docs that live outside the warehouse."
        ),
        npx_package="@modelcontextprotocol/server-notion",
        required_credentials=("NOTION_API_KEY",),
        docs_url="https://developers.notion.com/docs/create-a-notion-integration",
    ),
    "gdrive": MCPCatalogEntry(
        server_name="gdrive",
        display_name="Google Drive",
        description=(
            "Search Drive and read documents. Authentication uses Google's "
            "OAuth2 flow rather than a static token."
        ),
        npx_package="@modelcontextprotocol/server-gdrive",
        # OAuth2 credentials are stored under different keys after callback;
        # the catalog still lists them so the form knows what to surface.
        required_credentials=("GOOGLE_OAUTH_REFRESH_TOKEN",),
        oauth_flow="oauth2",
        docs_url="https://developers.google.com/drive",
    ),
}


class MCPCatalog:
    """Read-only static catalog. All access goes through classmethods."""

    @classmethod
    def all(cls) -> tuple[MCPCatalogEntry, ...]:
        """Stable iteration order, useful for tests + UI listings."""
        return tuple(_ENTRIES[k] for k in sorted(_ENTRIES))

    @classmethod
    def get(cls, server_name: str) -> Optional[MCPCatalogEntry]:
        return _ENTRIES.get(server_name)

    @classmethod
    def names(cls) -> frozenset[str]:
        return frozenset(_ENTRIES.keys())
