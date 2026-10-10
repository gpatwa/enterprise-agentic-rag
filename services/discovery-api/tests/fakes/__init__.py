"""Deterministic in-memory providers for discovery tests."""

from .discovery import (
    FakeCandidate,
    FakeCandidateSource,
    FakeConfig,
    FakeDiscoveryRepository,
    FakeFeature,
    FakeFeatureProvider,
    FakeMode,
    FakeProviderError,
    FakeRankedCandidate,
    FakeRanker,
    FakeTimeoutError,
    TraceEntry,
)

__all__ = [
    "FakeCandidate",
    "FakeCandidateSource",
    "FakeConfig",
    "FakeDiscoveryRepository",
    "FakeFeature",
    "FakeFeatureProvider",
    "FakeMode",
    "FakeProviderError",
    "FakeRanker",
    "FakeRankedCandidate",
    "FakeTimeoutError",
    "TraceEntry",
]
