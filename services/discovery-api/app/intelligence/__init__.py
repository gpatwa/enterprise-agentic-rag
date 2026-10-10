"""Optional, provider-independent intelligence contracts for discovery."""

from app.intelligence.intent import (
    INTENT_VERSION,
    MAX_CATALOG_IDS,
    MAX_EXPANSIONS,
    StructuredDiscoveryIntent,
    build_intent,
)

__all__ = [
    "INTENT_VERSION",
    "MAX_CATALOG_IDS",
    "MAX_EXPANSIONS",
    "StructuredDiscoveryIntent",
    "build_intent",
]
