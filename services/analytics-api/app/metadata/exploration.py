"""Review-only exploratory metadata handling."""
from __future__ import annotations

from dataclasses import dataclass

from packages.platform_contracts.metadata import MetadataAsset, MetadataQualityReport


@dataclass(frozen=True)
class ExploratoryDiscovery:
    asset: MetadataAsset
    quality: MetadataQualityReport
    execution_allowed: bool = False
    review_required: bool = True


def create_exploratory_discovery(asset: MetadataAsset, quality: MetadataQualityReport) -> ExploratoryDiscovery:
    """Return a discovery object that is structurally incapable of automatic execution."""
    return ExploratoryDiscovery(asset=asset, quality=quality)
