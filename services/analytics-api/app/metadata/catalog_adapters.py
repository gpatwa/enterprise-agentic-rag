"""HTTP catalog adapters that normalize into the shared metadata model."""
from __future__ import annotations

from typing import Any

import httpx

from packages.platform_contracts.metadata import MetadataAsset, MetadataColumn, MetadataSnapshot


class DataHubMetadataProvider:
    """Read-only DataHub GraphQL adapter; transport is injectable for local tests."""

    provider_name = "datahub"

    def __init__(self, base_url: str, token: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )

    def get_snapshot(self, asset_name: str) -> MetadataSnapshot:
        query = """
        query Dataset($urn: String!) {
          dataset(urn: $urn) {
            urn name properties { name description }
            ownership { owners { owner { urn } } }
            editableProperties { description }
            schemaMetadata { fields { fieldPath nativeDataType description } }
          }
        }
        """
        response = self.client.post(
            f"{self.base_url}/api/graphql",
            json={"query": query, "variables": {"urn": asset_name}},
        )
        response.raise_for_status()
        dataset: dict[str, Any] = response.json().get("data", {}).get("dataset") or {}
        fields = dataset.get("schemaMetadata", {}).get("fields", [])
        description = (
            dataset.get("editableProperties", {}).get("description")
            or dataset.get("properties", {}).get("description")
        )
        owners = [str(item.get("owner", {}).get("urn")) for item in dataset.get("ownership", {}).get("owners", [])]
        return MetadataSnapshot(
            provider=self.provider_name,
            assets=[
                MetadataAsset(
                    id=str(dataset.get("urn", asset_name)),
                    display_name=str(dataset.get("name", asset_name)),
                    physical_name=asset_name,
                    provider=self.provider_name,
                    description=description,
                    owner_ids=[owner for owner in owners if owner != "None"],
                    columns=[
                        MetadataColumn(
                            name=str(field.get("fieldPath", "unknown")),
                            data_type=str(field.get("nativeDataType", "unknown")),
                            description=field.get("description"),
                        )
                        for field in fields
                    ],
                )
            ],
        )
