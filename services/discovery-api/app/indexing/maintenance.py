"""Deterministic maintenance operations for a derived discovery index.

The implementation is deliberately provider-neutral.  It models the safety
checks that an OpenSearch adapter must enforce without making a network call or
mutating canonical catalog data.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Mapping

MAX_DOCUMENTS = 10_000
MAX_TOMBSTONES = 10_000
MAX_GENERATIONS = 32
MAX_ALIAS_HISTORY = 16
_EMPTY_CHECKSUM = hashlib.sha256(b"").hexdigest()


class MaintenanceError(ValueError):
    """Raised when an unsafe or inconsistent maintenance operation is requested."""


class DryRunRequired(MaintenanceError):
    """Raised when a destructive operation was not previewed first."""


class ChecksumMismatch(MaintenanceError):
    """Raised when supplied evidence does not match the derived index state."""


@dataclass(frozen=True, slots=True)
class Tombstone:
    """A derived-index deletion marker; it never deletes canonical catalog data."""

    document_id: str
    tenant_id: str
    reason: str
    source_version: str

    def __post_init__(self) -> None:
        _require_id(self.document_id, "document_id")
        _require_id(self.tenant_id, "tenant_id")
        _require_id(self.reason, "reason")
        _require_id(self.source_version, "source_version")


@dataclass(frozen=True, slots=True)
class RebuildManifest:
    """Bounded, immutable evidence for one derived-index rebuild."""

    generation: str
    document_ids: tuple[str, ...]
    document_count: int
    document_checksum: str
    tombstone_count: int = 0

    def __post_init__(self) -> None:
        _require_id(self.generation, "generation")
        if len(self.document_ids) > MAX_DOCUMENTS:
            raise MaintenanceError("rebuild exceeds the bounded document limit")
        if tuple(sorted(set(self.document_ids))) != self.document_ids:
            raise MaintenanceError("manifest document IDs must be sorted and unique")
        for document_id in self.document_ids:
            _require_id(document_id, "document_id")
        if self.document_count != len(self.document_ids):
            raise MaintenanceError("manifest document count does not match IDs")
        if self.document_checksum != checksum_ids(self.document_ids):
            raise ChecksumMismatch("manifest document checksum does not match IDs")
        if not 0 <= self.tombstone_count <= MAX_TOMBSTONES:
            raise MaintenanceError("tombstone count is outside the bounded limit")


@dataclass(frozen=True, slots=True)
class GenerationAlias:
    """Validated immutable generation metadata behind a logical alias."""

    alias: str
    generation: str
    document_count: int
    document_checksum: str
    validated: bool = False

    def __post_init__(self) -> None:
        _require_id(self.alias, "alias")
        _require_id(self.generation, "generation")
        if not 0 <= self.document_count <= MAX_DOCUMENTS:
            raise MaintenanceError("alias document count is outside the bounded limit")
        if len(self.document_checksum) != 64:
            raise MaintenanceError("alias checksum must be a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Redacted bounded evidence from comparing expected and indexed IDs."""

    generation: str
    expected_count: int
    actual_count: int
    expected_checksum: str
    actual_checksum: str
    missing_count: int
    unexpected_count: int
    matches: bool


@dataclass(frozen=True, slots=True)
class MaintenancePreview:
    """An immutable approval token for a destructive operation."""

    operation: str
    target: str
    fingerprint: str


def checksum_ids(document_ids: Iterable[str]) -> str:
    """Return a stable checksum for a sorted, unique ID collection."""
    normalized = _normalize_ids(document_ids)
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()


class IndexMaintenance:
    """In-memory fake index used to exercise safe maintenance semantics."""

    def __init__(self, *, alias: str = "imd-catalog-read") -> None:
        _require_id(alias, "alias")
        self._alias_name = alias
        self._generations: dict[str, tuple[str, ...]] = {}
        self._aliases: dict[str, GenerationAlias] = {}
        self._alias_history: list[GenerationAlias] = []
        self._tombstones: dict[str, Tombstone] = {}
        self._previews: dict[str, MaintenancePreview] = {}
        self._dry_runs: set[str] = set()

    @property
    def tombstones(self) -> tuple[Tombstone, ...]:
        return tuple(self._tombstones[key] for key in sorted(self._tombstones))

    @property
    def aliases(self) -> Mapping[str, GenerationAlias]:
        return dict(self._aliases)

    @property
    def generations(self) -> Mapping[str, tuple[str, ...]]:
        return dict(self._generations)

    def preview_rebuild(
        self,
        generation: str,
        document_ids: Iterable[str],
        *,
        tombstones: Iterable[Tombstone] = (),
    ) -> RebuildManifest:
        """Build immutable evidence for a rebuild, excluding tombstoned IDs."""
        _require_id(generation, "generation")
        requested = set(_normalize_ids(document_ids))
        supplied_tombstones = tuple(tombstones)
        if len(supplied_tombstones) > MAX_TOMBSTONES:
            raise MaintenanceError("rebuild exceeds the bounded tombstone limit")
        for tombstone in supplied_tombstones:
            existing = self._tombstones.get(tombstone.document_id)
            if existing is not None and existing != tombstone:
                raise MaintenanceError("conflicting tombstone for document ID")
        excluded = {item.document_id for item in supplied_tombstones} | set(self._tombstones)
        selected = tuple(sorted(requested - excluded))
        manifest = RebuildManifest(
            generation=generation,
            document_ids=selected,
            document_count=len(selected),
            document_checksum=checksum_ids(selected),
            tombstone_count=len(excluded & requested),
        )
        fingerprint = self._fingerprint("rebuild", generation, manifest.document_checksum)
        self._previews[fingerprint] = MaintenancePreview(
            "rebuild", generation, fingerprint
        )
        return manifest

    def apply_rebuild(self, manifest: RebuildManifest, *, dry_run: bool = False) -> None:
        """Install a validated rebuild only after its preview gate is satisfied."""
        preview = self._previews.get(
            self._fingerprint("rebuild", manifest.generation, manifest.document_checksum)
        )
        if preview is None:
            raise DryRunRequired("rebuild must be previewed before apply")
        if dry_run:
            self._dry_runs.add(preview.fingerprint)
            return
        if preview.fingerprint not in self._dry_runs:
            raise DryRunRequired("rebuild dry-run must complete before apply")
        if len(self._generations) >= MAX_GENERATIONS and manifest.generation not in self._generations:
            raise MaintenanceError("generation limit exceeded")
        self._generations[manifest.generation] = manifest.document_ids
        self._aliases[manifest.generation] = GenerationAlias(
            alias=manifest.generation,
            generation=manifest.generation,
            document_count=manifest.document_count,
            document_checksum=manifest.document_checksum,
            validated=True,
        )
        del self._previews[preview.fingerprint]
        self._dry_runs.discard(preview.fingerprint)

    def preview_tombstone(self, tombstone: Tombstone) -> MaintenancePreview:
        """Create the explicit preview required before recording a tombstone."""
        existing = self._tombstones.get(tombstone.document_id)
        if existing is not None and existing != tombstone:
            raise MaintenanceError("conflicting tombstone for document ID")
        preview = MaintenancePreview(
            "tombstone", tombstone.document_id, _tombstone_fingerprint(tombstone)
        )
        self._previews[preview.fingerprint] = preview
        return preview

    def apply_tombstone(self, tombstone: Tombstone, *, dry_run: bool = False) -> None:
        preview = self._previews.get(_tombstone_fingerprint(tombstone))
        if preview is None:
            raise DryRunRequired("tombstone must be previewed before apply")
        if dry_run:
            self._dry_runs.add(preview.fingerprint)
            return
        if preview.fingerprint not in self._dry_runs:
            raise DryRunRequired("tombstone dry-run must complete before apply")
        self._tombstones[tombstone.document_id] = tombstone
        for generation, ids in self._generations.items():
            self._generations[generation] = tuple(
                item for item in ids if item != tombstone.document_id
            )
        del self._previews[preview.fingerprint]
        self._dry_runs.discard(preview.fingerprint)

    def reconcile(
        self,
        generation: str,
        expected_ids: Iterable[str],
        *,
        expected_checksum: str | None = None,
    ) -> ReconciliationResult:
        expected = _normalize_ids(expected_ids)
        actual = self._generations.get(generation)
        if actual is None:
            raise MaintenanceError("generation does not exist")
        expected_digest = checksum_ids(expected)
        if expected_checksum is not None and expected_checksum != expected_digest:
            raise ChecksumMismatch("expected checksum does not match expected IDs")
        expected_set = set(expected)
        actual_set = set(actual)
        return ReconciliationResult(
            generation=generation,
            expected_count=len(expected),
            actual_count=len(actual),
            expected_checksum=expected_digest,
            actual_checksum=checksum_ids(actual),
            missing_count=len(expected_set - actual_set),
            unexpected_count=len(actual_set - expected_set),
            matches=expected == actual,
        )

    def preview_swap(self, generation: str) -> MaintenancePreview:
        alias = self._aliases.get(generation)
        if alias is None or not alias.validated:
            raise MaintenanceError("only validated generations can become active")
        fingerprint = self._fingerprint("swap", self._alias_name, generation)
        preview = MaintenancePreview("swap", self._alias_name, fingerprint)
        self._previews[fingerprint] = preview
        return preview

    def apply_swap(self, generation: str, *, dry_run: bool = False) -> None:
        preview = self._previews.get(self._fingerprint("swap", self._alias_name, generation))
        if preview is None:
            raise DryRunRequired("alias swap must be previewed before apply")
        if dry_run:
            self._dry_runs.add(preview.fingerprint)
            return
        if preview.fingerprint not in self._dry_runs:
            raise DryRunRequired("alias swap dry-run must complete before apply")
        prior = self._aliases.get(self._alias_name)
        if prior is not None:
            self._alias_history.append(prior)
            del self._alias_history[:-MAX_ALIAS_HISTORY]
        target = self._aliases[generation]
        self._aliases[self._alias_name] = GenerationAlias(
            alias=self._alias_name,
            generation=target.generation,
            document_count=target.document_count,
            document_checksum=target.document_checksum,
            validated=True,
        )
        del self._previews[preview.fingerprint]
        self._dry_runs.discard(preview.fingerprint)

    def preview_rollback(self) -> MaintenancePreview:
        if not self._alias_history:
            raise MaintenanceError("no validated prior alias is available")
        fingerprint = self._fingerprint("rollback", self._alias_name, self._alias_history[-1].generation)
        preview = MaintenancePreview("rollback", self._alias_name, fingerprint)
        self._previews[fingerprint] = preview
        return preview

    def apply_rollback(self, *, dry_run: bool = False) -> None:
        if not self._alias_history:
            raise MaintenanceError("no validated prior alias is available")
        prior = self._alias_history[-1]
        preview = self._previews.get(self._fingerprint("rollback", self._alias_name, prior.generation))
        if preview is None:
            raise DryRunRequired("rollback must be previewed before apply")
        if dry_run:
            self._dry_runs.add(preview.fingerprint)
            return
        if preview.fingerprint not in self._dry_runs:
            raise DryRunRequired("rollback dry-run must complete before apply")
        self._aliases[self._alias_name] = prior
        self._alias_history.pop()
        del self._previews[preview.fingerprint]
        self._dry_runs.discard(preview.fingerprint)

    @staticmethod
    def _fingerprint(operation: str, target: str, value: str) -> str:
        return hashlib.sha256(f"{operation}\x00{target}\x00{value}".encode()).hexdigest()


def _tombstone_fingerprint(tombstone: Tombstone) -> str:
    material = "\x00".join(
        (tombstone.document_id, tombstone.tenant_id, tombstone.reason, tombstone.source_version)
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _normalize_ids(document_ids: Iterable[str]) -> tuple[str, ...]:
    values = tuple(document_ids)
    if len(values) > MAX_DOCUMENTS:
        raise MaintenanceError("document collection exceeds the bounded limit")
    for document_id in values:
        _require_id(document_id, "document_id")
    return tuple(sorted(set(values)))


def _require_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise MaintenanceError(f"{field_name} must be a non-blank bounded string")
