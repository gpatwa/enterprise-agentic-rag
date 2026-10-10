from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class MappingCompatibilityKind(str, Enum):
    IDENTICAL = "identical"
    ADDITIVE = "additive"
    BREAKING = "breaking"


@dataclass(frozen=True)
class MappingCompatibility:
    kind: MappingCompatibilityKind
    reasons: tuple[str, ...] = ()

    @property
    def is_compatible(self) -> bool:
        return self.kind in {
            MappingCompatibilityKind.IDENTICAL,
            MappingCompatibilityKind.ADDITIVE,
        }


def classify_mapping_compatibility(
    existing: dict[str, Any],
    proposed: dict[str, Any],
) -> MappingCompatibility:
    """Classify whether a proposed OpenSearch mapping adds or breaks fields."""
    if existing == proposed:
        return MappingCompatibility(MappingCompatibilityKind.IDENTICAL)

    reasons: list[str] = []
    additive = True

    existing_properties = existing.get("properties", {})
    proposed_properties = proposed.get("properties", {})
    if not isinstance(existing_properties, dict) or not isinstance(proposed_properties, dict):
        return MappingCompatibility(
            MappingCompatibilityKind.BREAKING,
            ("mapping properties must be objects",),
        )

    for field_name in sorted(existing_properties):
        if field_name not in proposed_properties:
            additive = False
            reasons.append(f"field removed: {field_name}")
            continue
        if existing_properties[field_name] != proposed_properties[field_name]:
            additive = False
            reasons.append(f"field definition changed: {field_name}")

    for field_name in sorted(proposed_properties):
        if field_name not in existing_properties:
            reasons.append(f"field added: {field_name}")

    for key in sorted((set(existing) | set(proposed)) - {"properties"}):
        if key == "properties":
            continue
        if existing.get(key) != proposed.get(key):
            additive = False
            reasons.append(f"mapping setting changed: {key}")

    if additive and reasons:
        return MappingCompatibility(MappingCompatibilityKind.ADDITIVE, tuple(reasons))
    return MappingCompatibility(MappingCompatibilityKind.BREAKING, tuple(reasons))


compare_mappings = classify_mapping_compatibility
