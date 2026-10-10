"""Deterministic, local-only JSONL event-lake storage."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.events.models import InteractionEvent, InteractionEventBatch

_SCHEMA_VERSION = "v1"
_DEFAULT_READ_LIMIT = 1_000


@dataclass(frozen=True)
class PartitionManifest:
    """Checksummed metadata for one canonical JSONL partition."""

    tenant_id: str
    event_date: str
    event_type: str
    path: str
    event_count: int
    byte_size: int
    checksum_sha256: str


@dataclass(frozen=True)
class EventLakeManifest:
    """The durable receipt for one append operation."""

    schema_version: str
    manifest_id: str
    created_at: str
    event_count: int
    byte_size: int
    checksum_sha256: str
    partitions: tuple[PartitionManifest, ...]
    path: str

    def serialize(self) -> str:
        return json.dumps(
            asdict(self), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )


class EventLakeWriter:
    """Append synthetic interaction events to deterministic local partitions.

    The root directory is deliberately a plain filesystem boundary. Existing
    event IDs are replay-safe only when their canonical bytes match; a changed
    event with the same ID is rejected rather than silently overwritten.
    """

    def __init__(self, root: str | Path, *, max_read_events: int = _DEFAULT_READ_LIMIT) -> None:
        if isinstance(max_read_events, bool) or not 1 <= max_read_events <= 100_000:
            raise ValueError("max_read_events must be between 1 and 100000")
        self.root = Path(root)
        self.max_read_events = max_read_events

    def append(
        self,
        records: InteractionEventBatch | Iterable[InteractionEvent],
        *,
        manifest_id: str | None = None,
    ) -> EventLakeManifest:
        events = self._normalise_records(records)
        self._validate_batch(events)
        existing = self._existing_events()
        new_events: list[InteractionEvent] = []
        for event in events:
            canonical = event.serialize()
            prior = existing.get(event.event_id)
            if prior is not None:
                if prior != canonical:
                    raise ValueError(f"event ID {event.event_id!r} already exists with different content")
                continue
            new_events.append(event)

        groups: dict[tuple[str, str, str], list[InteractionEvent]] = {}
        for event in new_events:
            key = self._partition_key(event)
            groups.setdefault(key, []).append(event)

        partition_manifests: list[PartitionManifest] = []
        for key in sorted(groups):
            partition_manifests.append(self._append_partition(key, groups[key]))

        if manifest_id is None:
            manifest_id = self._manifest_id(events)
        self._validate_manifest_id(manifest_id)
        manifest_payload = {
            "schema_version": _SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "event_count": len(new_events),
            "byte_size": sum(item.byte_size for item in partition_manifests),
            "checksum_sha256": self._combined_checksum(partition_manifests),
        }
        manifest_json = {**manifest_payload, "partitions": [asdict(item) for item in partition_manifests]}
        manifest_path = self.root / "manifests" / f"{manifest_id}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest_json, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return EventLakeManifest(
            **manifest_payload,
            partitions=tuple(partition_manifests),
            path=self._relative(manifest_path),
        )

    def read_partition(self, path: str | Path, *, limit: int | None = None) -> tuple[InteractionEvent, ...]:
        """Read at most the configured bound of events from one partition."""
        bound = self.max_read_events if limit is None else limit
        if isinstance(bound, bool) or not 1 <= bound <= self.max_read_events:
            raise ValueError(f"limit must be between 1 and {self.max_read_events}")
        partition = self._resolve_path(path)
        events: list[InteractionEvent] = []
        with partition.open(encoding="utf-8") as handle:
            for line in handle:
                if len(events) >= bound:
                    break
                if line.strip():
                    events.append(InteractionEvent.model_validate_json(line))
        return tuple(events)

    def read_manifest(self, path: str | Path) -> EventLakeManifest:
        """Read and validate a previously emitted manifest."""
        manifest_path = self._resolve_path(path)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        partitions = tuple(PartitionManifest(**item) for item in payload.pop("partitions"))
        payload["partitions"] = partitions
        payload["path"] = self._relative(manifest_path)
        return EventLakeManifest(**payload)

    def _append_partition(
        self, key: tuple[str, str, str], events: list[InteractionEvent]
    ) -> PartitionManifest:
        tenant_id, event_date, event_type = key
        path = self.root / "events" / f"tenant={tenant_id}" / f"date={event_date}" / f"event_type={event_type}" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(events, key=lambda item: (item.occurred_at, item.event_id))
        lines = "".join(f"{event.serialize()}\n" for event in ordered).encode("utf-8")
        if path.exists():
            prior = path.read_bytes()
            if prior and not prior.endswith(b"\n"):
                raise ValueError(f"partition {self._relative(path)!r} is not newline terminated")
            path.write_bytes(prior + lines)
        else:
            path.write_bytes(lines)
        content = path.read_bytes()
        return PartitionManifest(
            tenant_id=tenant_id,
            event_date=event_date,
            event_type=event_type,
            path=self._relative(path),
            event_count=len(ordered),
            byte_size=len(lines),
            checksum_sha256=hashlib.sha256(content).hexdigest(),
        )

    def _existing_events(self) -> dict[str, str]:
        existing: dict[str, str] = {}
        events_root = self.root / "events"
        if not events_root.exists():
            return existing
        for path in sorted(events_root.rglob("events.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                event = InteractionEvent.model_validate_json(line)
                canonical = event.serialize()
                prior = existing.setdefault(event.event_id, canonical)
                if prior != canonical:
                    raise ValueError(f"event ID {event.event_id!r} is duplicated with different content")
        return existing

    @staticmethod
    def _normalise_records(
        records: InteractionEventBatch | Iterable[InteractionEvent],
    ) -> tuple[InteractionEvent, ...]:
        if isinstance(records, InteractionEventBatch):
            return records.events
        events = tuple(records)
        if not events:
            raise ValueError("at least one event is required")
        return events

    @staticmethod
    def _validate_batch(events: tuple[InteractionEvent, ...]) -> None:
        tenant_ids = {event.tenant_id for event in events}
        if len(tenant_ids) != 1:
            raise ValueError("a batch must contain one tenant")
        event_ids = [event.event_id for event in events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("event IDs must be unique within a batch")
        if any(not event.synthetic for event in events):
            raise ValueError("local event lake accepts synthetic events only")

    @staticmethod
    def _partition_key(event: InteractionEvent) -> tuple[str, str, str]:
        event_date = event.occurred_at.astimezone(timezone.utc).date().isoformat()
        return event.tenant_id, event_date, event.event_type.value

    @staticmethod
    def _manifest_id(events: tuple[InteractionEvent, ...]) -> str:
        digest = hashlib.sha256("\n".join(event.serialize() for event in events).encode("utf-8")).hexdigest()
        return f"manifest-{digest[:32]}"

    @staticmethod
    def _validate_manifest_id(manifest_id: str) -> None:
        if not manifest_id or "/" in manifest_id or "\\" in manifest_id or manifest_id in {".", ".."}:
            raise ValueError("manifest_id must be a non-empty path-safe value")

    def _resolve_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        resolved = candidate if candidate.is_absolute() else self.root / candidate
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("path must remain inside the event-lake root") from exc
        return resolved

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    @staticmethod
    def _combined_checksum(partitions: list[PartitionManifest]) -> str:
        value = "\n".join(f"{item.path}:{item.checksum_sha256}" for item in partitions)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
