"""Incremental metadata refresh and immutable context-snapshot publication (ADS-044).

One worker run fetches every configured source (dbt artifacts, OpenMetadata, direct
inspection), keeps the last good copy of a source that fails, tombstones assets a
healthy source stopped reporting, merges by explicit precedence, applies the context
quality gate, and only then publishes. The published pointer advances solely after
publication (and the optional index hook) succeeds, and readers fail closed when the
pointer has not been re-verified within the staleness window.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from app.context.quality import evaluate_context_quality
from app.context.snapshot_registry import ContextSnapshotNotFoundError, ContextSnapshotRegistry
from app.metadata.providers import DbtManifestProvider, MetadataProvider
from packages.platform_contracts.context_merge import (
    DEFAULT_SOURCE_PRECEDENCE,
    MetadataTombstone,
    merge_metadata_snapshots,
)
from packages.platform_contracts.context_snapshot import ContextSnapshot
from packages.platform_contracts.metadata import MetadataAsset, MetadataFreshness, MetadataSnapshot
from packages.platform_contracts.ontology import OntologySnapshot


class SourceFetchError(RuntimeError):
    """A source could not be read; the message must not carry credentials or payloads."""


class StaleSnapshotError(LookupError):
    pass


class NoSnapshotError(LookupError):
    pass


class RefreshSource(Protocol):
    name: str

    def fetch(self) -> MetadataSnapshot: ...


class OntologyRefreshSource(Protocol):
    name: str

    def fetch(self) -> OntologySnapshot: ...


class OntologyFileRefreshSource:
    """Read an `OntologySnapshot` JSON document (for example a Git checkout) on every run.

    The source is a pass-through: node and edge lifecycles come from the document and
    are never promoted here. Certification is a human gate that happens upstream of
    this file; a candidate node stays a candidate.
    """

    def __init__(self, path: Path | str, *, tenant_id: str, name: str = "ontology"):
        self.path = Path(path)
        self.tenant_id = tenant_id
        self.name = name

    def fetch(self) -> OntologySnapshot:
        try:
            snapshot = OntologySnapshot.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # pydantic's ValidationError is a ValueError
            raise SourceFetchError(f"{self.name} unreadable: {type(exc).__name__}") from exc
        if snapshot.tenant_id != self.tenant_id:
            raise SourceFetchError(f"{self.name} tenant does not match the refresh tenant")
        return snapshot


class ProviderRefreshSource:
    """Fetch a fixed asset list through a `MetadataProvider`.

    An asset the catalog reports as missing (HTTP 404 or an empty snapshot) is simply
    absent from the result; every other failure aborts the fetch so a partial read is
    never mistaken for deletions.
    """

    def __init__(self, provider: MetadataProvider, asset_names: Sequence[str], *, name: str | None = None):
        self.provider = provider
        self.asset_names = tuple(asset_names)
        self.name = name or provider.provider_name

    def fetch(self) -> MetadataSnapshot:
        assets: dict[str, MetadataAsset] = {}
        for asset_name in self.asset_names:
            try:
                snapshot = self.provider.get_snapshot(asset_name)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                raise SourceFetchError(f"{self.name} returned HTTP {exc.response.status_code}") from exc
            except Exception as exc:  # noqa: BLE001 - normalize driver/network errors without payloads.
                raise SourceFetchError(f"{self.name} fetch failed: {type(exc).__name__}") from exc
            for asset in snapshot.assets:
                if asset.source_version is None:
                    # Catalogs that expose no revision still get a verifiable provenance tag:
                    # the digest of the content as observed (observation time excluded).
                    digest = _hash(_normalized(asset))[:16]
                    asset = asset.model_copy(update={"source_version": f"{self.name}:sha256:{digest}"})
                assets[asset.id] = asset
        return MetadataSnapshot(provider=self.name, assets=list(assets.values()))


class DbtArtifactRefreshSource(ProviderRefreshSource):
    """Re-read dbt manifest/catalog/run_results from disk on every run."""

    def __init__(
        self,
        manifest_path: Path | str,
        model_names: Sequence[str],
        *,
        catalog_path: Path | str | None = None,
        run_results_path: Path | str | None = None,
    ):
        self._paths = (manifest_path, catalog_path, run_results_path)
        super().__init__(DbtManifestProvider({}), model_names, name="dbt")

    def fetch(self) -> MetadataSnapshot:
        try:
            self.provider = DbtManifestProvider.from_files(*self._paths)
        except (OSError, ValueError) as exc:
            raise SourceFetchError(f"dbt artifacts unreadable: {type(exc).__name__}") from exc
        return super().fetch()


@dataclass(frozen=True)
class StalenessPolicy:
    max_source_age: timedelta = timedelta(hours=6)
    max_snapshot_age: timedelta = timedelta(hours=24)


@dataclass(frozen=True)
class SourceOutcome:
    status: Literal["fetched", "failed", "reused_stale"]
    error: str | None = None
    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefreshReport:
    status: Literal["published", "unchanged", "blocked", "failed"]
    snapshot_id: str | None = None
    sources: dict[str, SourceOutcome] = field(default_factory=dict)
    tombstoned_asset_ids: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    resolved_conflicts: int = 0
    ontology: SourceOutcome | None = None


class RefreshStateStore:
    """Atomic JSON state per tenant: per-source last-good assets, tombstones, pointer."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def load(self, tenant_id: str) -> dict[str, Any]:
        try:
            return json.loads(self._path(tenant_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"sources": {}, "tombstones": [], "current": None}

    def save(self, tenant_id: str, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix=".refresh-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(state, sort_keys=True, default=str))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(tenant_id))
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise

    def _path(self, tenant_id: str) -> Path:
        return self.root / f"refresh-{hashlib.sha256(tenant_id.encode()).hexdigest()}.json"


class ContextRefreshWorker:
    def __init__(
        self,
        *,
        tenant_id: str,
        sources: Sequence[RefreshSource],
        registry: ContextSnapshotRegistry,
        state: RefreshStateStore,
        policy: StalenessPolicy = StalenessPolicy(),
        precedence: tuple[str, ...] = DEFAULT_SOURCE_PRECEDENCE,
        semantic_contract_ids: tuple[str, ...] = (),
        ontology_source: OntologyRefreshSource | None = None,
        on_publish: Callable[[ContextSnapshot], None] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        names = [source.name for source in sources]
        if not names or len(set(names)) != len(names):
            raise ValueError("refresh sources must be non-empty with unique names")
        self.tenant_id = tenant_id
        self.sources = tuple(sources)
        self.registry = registry
        self.state_store = state
        self.policy = policy
        self.precedence = precedence
        self.semantic_contract_ids = semantic_contract_ids
        self.ontology_source = ontology_source
        self.on_publish = on_publish
        self.clock = clock

    def run_once(self) -> RefreshReport:
        now = self.clock()
        state = self.state_store.load(self.tenant_id)
        outcomes: dict[str, SourceOutcome] = {}
        tombstones = {item["asset_id"]: item for item in state["tombstones"]}
        for source in self.sources:
            previous = state["sources"].get(source.name)
            try:
                fetched = source.fetch()
            except SourceFetchError as exc:
                outcomes[source.name] = SourceOutcome("failed", error=str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 - one broken source must not abort the cycle.
                outcomes[source.name] = SourceOutcome("failed", error=f"{type(exc).__name__}")
                continue
            previous_assets = {item["id"]: item for item in (previous or {}).get("assets", [])}
            if not fetched.assets and previous_assets:
                # An empty read after a populated one is an outage signature, not mass deletion.
                outcomes[source.name] = SourceOutcome("failed", error="empty fetch after populated state")
                continue
            current = {asset.id: _normalized(asset) for asset in fetched.assets}
            added = tuple(sorted(set(current) - set(previous_assets)))
            removed = tuple(sorted(set(previous_assets) - set(current)))
            updated = tuple(
                sorted(
                    key
                    for key in set(current) & set(previous_assets)
                    if _hash(current[key]) != _hash(_normalized_dump(previous_assets[key]))
                )
            )
            for asset_id in removed:
                tombstones[asset_id] = {
                    "asset_id": asset_id,
                    "source": source.name,
                    "source_version": previous_assets[asset_id].get("source_version") or "unversioned",
                    "observed_at": now.isoformat(),
                    "reason": "asset no longer reported by source",
                }
            for asset_id in current:  # an asset reappearing from the same source lifts its tombstone
                if tombstones.get(asset_id, {}).get("source") == source.name:
                    del tombstones[asset_id]
            state["sources"][source.name] = {
                "assets": [asset.model_dump(mode="json") for asset in fetched.assets],
                "last_success_at": now.isoformat(),
                "content_hash": _hash([current[key] for key in sorted(current)]),
            }
            outcomes[source.name] = SourceOutcome("fetched", added=added, updated=updated, removed=removed)

        ontology, ontology_outcome, ontology_stale = self._refresh_ontology(state, now)

        snapshots: list[MetadataSnapshot] = []
        for source in self.sources:
            cached = state["sources"].get(source.name)
            if cached is None:
                continue
            age = now - datetime.fromisoformat(cached["last_success_at"])
            stale = age > self.policy.max_source_age
            if outcomes[source.name].status == "failed":
                outcomes[source.name] = SourceOutcome(
                    "reused_stale" if stale else "failed", error=outcomes[source.name].error
                )
            snapshots.append(
                MetadataSnapshot(
                    provider=source.name,
                    assets=[_mark_stale(MetadataAsset.model_validate(item), stale) for item in cached["assets"]],
                )
            )
        if not snapshots:
            return RefreshReport("failed", sources=outcomes, blocking_reasons=("no source has ever succeeded",))

        merged = merge_metadata_snapshots(
            tuple(snapshots),
            tombstones=tuple(MetadataTombstone.model_validate(item) for item in tombstones.values()),
            precedence=self.precedence,
        )
        source_hashes = tuple(
            sorted(
                f"{source.name}:{state['sources'][source.name]['content_hash']}"
                for source in self.sources
                if source.name in state["sources"]
            )
        )
        tombstone_ids = tuple(sorted(item.asset_id for item in merged.applied_tombstones))
        content_hash = _hash(
            {
                "sources": source_hashes,
                "tombstones": tombstone_ids,
                "contracts": sorted(self.semantic_contract_ids),
                "ontology": _ontology_hash(ontology) if ontology else None,
                "assets": [_normalized(asset) for asset in merged.snapshot.assets],
            }
        )
        snapshot_id = f"refresh:{self.tenant_id}:{content_hash[:16]}"
        snapshot = ContextSnapshot.build(
            snapshot_id=snapshot_id,
            tenant_id=self.tenant_id,
            source_fingerprints=tuple(
                hashlib.sha256(item.encode()).hexdigest()
                for item in (*source_hashes, *((f"ontology:{_ontology_hash(ontology)}",) if ontology else ()))
            ),
            metadata_assets=tuple(merged.snapshot.assets),
            ontology=ontology,
            semantic_contract_ids=self.semantic_contract_ids,
            created_at=now,
        )
        # Precedence-resolved conflicts are reported, not blocking; staleness and provenance are.
        quality = evaluate_context_quality(snapshot, minimum_provenance=1.0)
        report = dict(
            sources=outcomes,
            tombstoned_asset_ids=tuple(sorted(tombstones)),
            resolved_conflicts=len(merged.conflicts),
            ontology=ontology_outcome,
        )
        failed = any(outcome.status == "failed" for outcome in outcomes.values()) or (
            ontology_outcome is not None and ontology_outcome.status == "failed"
        )
        reasons = (*quality.blocking_reasons, *(("stale ontology",) if ontology_stale else ()))
        if reasons:
            self._save(state, tombstones)
            return RefreshReport("blocked", blocking_reasons=reasons, **report)

        current = state["current"]
        if current and current["content_hash"] == content_hash and not failed:
            current["verified_at"] = now.isoformat()
            self._save(state, tombstones)
            return RefreshReport("unchanged", snapshot_id=current["snapshot_id"], **report)
        if failed and current and current["content_hash"] == content_hash:
            # Same content from last-good data only: do not renew the verification clock.
            self._save(state, tombstones)
            return RefreshReport("unchanged", snapshot_id=current["snapshot_id"], **report)

        try:  # same content hash => same ID: a retry after a hook failure reuses the stored snapshot
            snapshot = self.registry.get(snapshot_id, self.tenant_id)
        except ContextSnapshotNotFoundError:
            self.registry.publish(snapshot)
        if self.on_publish:
            try:
                self.on_publish(snapshot)
            except Exception as exc:  # noqa: BLE001 - leave the pointer on the previous snapshot.
                self._save(state, tombstones)
                return RefreshReport(
                    "blocked", blocking_reasons=(f"publish hook failed: {type(exc).__name__}",), **report
                )
        state["current"] = {
            "snapshot_id": snapshot_id,
            "content_hash": content_hash,
            "published_at": now.isoformat(),
            "verified_at": now.isoformat() if not failed else (current or {}).get("verified_at", now.isoformat()),
        }
        self._save(state, tombstones)
        return RefreshReport("published", snapshot_id=snapshot_id, **report)

    def _refresh_ontology(
        self, state: dict[str, Any], now: datetime
    ) -> tuple[OntologySnapshot | None, SourceOutcome | None, bool]:
        """Fetch the ontology, falling back to the last good copy; returns (graph, outcome, stale).

        Ontology is a complete graph per fetch, so absence means removal; no tombstones.
        """
        if self.ontology_source is None:
            return None, None, False
        cached = state.get("ontology")
        previous = OntologySnapshot.model_validate(cached["snapshot"]) if cached else None
        error: str | None = None
        try:
            fetched = self.ontology_source.fetch()
        except SourceFetchError as exc:
            fetched, error = None, str(exc)
        except Exception as exc:  # noqa: BLE001 - one broken source must not abort the cycle.
            fetched, error = None, type(exc).__name__
        if fetched is not None and fetched.tenant_id != self.tenant_id:
            fetched, error = None, "ontology tenant does not match the refresh tenant"
        if (
            fetched is not None
            and previous
            and (previous.nodes or previous.edges)
            and not (fetched.nodes or fetched.edges)
        ):
            fetched, error = None, "empty fetch after populated state"
        if fetched is None:
            if previous is None:
                return None, SourceOutcome("failed", error=error), False
            stale = now - datetime.fromisoformat(cached["last_success_at"]) > self.policy.max_source_age
            return previous, SourceOutcome("reused_stale" if stale else "failed", error=error), stale
        before = _ontology_items(previous) if previous else {}
        after = _ontology_items(fetched)
        state["ontology"] = {
            "snapshot": fetched.model_dump(mode="json"),
            "last_success_at": now.isoformat(),
        }
        return (
            fetched,
            SourceOutcome(
                "fetched",
                added=tuple(sorted(set(after) - set(before))),
                updated=tuple(sorted(k for k in set(after) & set(before) if after[k] != before[k])),
                removed=tuple(sorted(set(before) - set(after))),
            ),
            False,
        )

    def current_snapshot(self, *, now: datetime | None = None) -> ContextSnapshot:
        """Return the published snapshot, failing closed when it is stale or missing."""
        pointer = self.state_store.load(self.tenant_id)["current"]
        if not pointer:
            raise NoSnapshotError("no context snapshot has been published")
        moment = now or self.clock()
        if moment - datetime.fromisoformat(pointer["verified_at"]) > self.policy.max_snapshot_age:
            raise StaleSnapshotError("published context snapshot has not been refreshed within policy")
        try:
            return self.registry.get(pointer["snapshot_id"], self.tenant_id)
        except ContextSnapshotNotFoundError as exc:
            raise NoSnapshotError("published context snapshot is missing from the registry") from exc

    def _save(self, state: dict[str, Any], tombstones: dict[str, Any]) -> None:
        state["tombstones"] = sorted(tombstones.values(), key=lambda item: item["asset_id"])
        self.state_store.save(self.tenant_id, state)


def _strip_observed(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_observed(v) for k, v in value.items() if k != "observed_at"}
    if isinstance(value, list):
        return [_strip_observed(item) for item in value]
    return value


def _ontology_items(snapshot: OntologySnapshot) -> dict[str, str]:
    items = {node.node_id: _hash(_strip_observed(node.model_dump(mode="json"))) for node in snapshot.nodes}
    items.update(
        {f"edge:{edge.edge_id}": _hash(_strip_observed(edge.model_dump(mode="json"))) for edge in snapshot.edges}
    )
    return items


def _ontology_hash(snapshot: OntologySnapshot) -> str:
    return _hash(_ontology_items(snapshot))


def _normalized(asset: MetadataAsset) -> dict[str, Any]:
    return asset.model_dump(mode="json", exclude={"observed_at"})


def _normalized_dump(dumped: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dumped.items() if key != "observed_at"}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _mark_stale(asset: MetadataAsset, stale: bool) -> MetadataAsset:
    if not stale:
        return asset
    freshness = (asset.freshness or MetadataFreshness()).model_copy(update={"stale": True})
    return asset.model_copy(update={"freshness": freshness})
