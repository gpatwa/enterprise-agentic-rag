"""Immutable, provider-neutral resolution prompt/model/policy registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class ResolutionStage(StrEnum):
    INTENT = "intent"
    PLANNER = "planner"
    RERANKER = "reranker"
    SYNTHESIS = "synthesis"
    COMMAND = "command"
    POLICY = "policy"


_STAGES = tuple(ResolutionStage)


def _version(value: str, name: str = "version") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value.strip()


def _frozen_metadata(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    # Metadata is deliberately scalar: this keeps snapshots deterministic and
    # prevents a mutable nested object from entering the registry.
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("metadata keys must be non-blank strings")
        if not isinstance(item, (str, int, float, bool, type(None))):
            raise TypeError("metadata values must be scalar")
        result[key] = item
    return MappingProxyType(dict(sorted(result.items())))


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """One immutable stage release; it contains references, never secrets."""

    stage: ResolutionStage
    version: str
    prompt_version: str
    model_version: str
    policy_version: str
    provider: str = "provider-neutral"
    model_route: str = "default"
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", ResolutionStage(self.stage))
        for name in ("version", "prompt_version", "model_version", "policy_version"):
            _version(getattr(self, name), name)
        _version(self.provider, "provider")
        _version(self.model_route, "model_route")
        object.__setattr__(self, "metadata", _frozen_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """Deterministic point-in-time registry; registration returns a new snapshot."""

    entries: Mapping[ResolutionStage, Mapping[str, RegistryEntry]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[ResolutionStage, Mapping[str, RegistryEntry]] = {}
        for stage in _STAGES:
            source = self.entries.get(stage, {})
            values: dict[str, RegistryEntry] = {}
            for version, entry in source.items():
                if not isinstance(entry, RegistryEntry) or entry.stage is not stage:
                    raise ValueError("registry entry stage does not match its bucket")
                if _version(version) != entry.version:
                    raise ValueError("registry key does not match entry version")
                values[version] = entry
            normalized[stage] = MappingProxyType(dict(sorted(values.items())))
        object.__setattr__(self, "entries", MappingProxyType(normalized))

    def register(self, entry: RegistryEntry) -> "RegistrySnapshot":
        if not isinstance(entry, RegistryEntry):
            raise TypeError("entry must be a RegistryEntry")
        updated = {stage: dict(values) for stage, values in self.entries.items()}
        updated[entry.stage][entry.version] = entry
        return RegistrySnapshot(updated)

    def resolve(self, stage: ResolutionStage | str, version: str) -> RegistryEntry:
        stage = ResolutionStage(stage)
        version = _version(version)
        try:
            return self.entries[stage][version]
        except KeyError as exc:
            raise LookupError(f"unknown {stage.value} registry version: {version}") from exc


def empty_registry() -> RegistrySnapshot:
    return RegistrySnapshot()


__all__ = ["RegistryEntry", "RegistrySnapshot", "ResolutionStage", "empty_registry"]
