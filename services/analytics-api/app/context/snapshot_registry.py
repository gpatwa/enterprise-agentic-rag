"""Immutable local context snapshot store with tenant-scoped lookup."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from packages.platform_contracts.context_snapshot import ContextSnapshot


class ContextSnapshotConflictError(ValueError):
    pass


class ContextSnapshotNotFoundError(LookupError):
    pass


class ContextSnapshotRegistry:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def publish(self, snapshot: ContextSnapshot) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(snapshot.snapshot_id, snapshot.tenant_id)
        payload = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix=".snapshot-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                existing = self.get(snapshot.snapshot_id, snapshot.tenant_id)
                if existing.content_fingerprint != snapshot.content_fingerprint:
                    raise ContextSnapshotConflictError(
                        "snapshot IDs are immutable and already contain different content"
                    )
        finally:
            os.unlink(temporary)

    def get(self, snapshot_id: str, tenant_id: str) -> ContextSnapshot:
        path = self._path(snapshot_id, tenant_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ContextSnapshotNotFoundError("context snapshot does not exist for tenant") from exc
        snapshot = ContextSnapshot.model_validate(value)
        if snapshot.snapshot_id != snapshot_id or snapshot.tenant_id != tenant_id:
            raise ContextSnapshotNotFoundError("context snapshot identity does not match tenant")
        return snapshot

    def _path(self, snapshot_id: str, tenant_id: str) -> Path:
        key = hashlib.sha256(f"{tenant_id}\0{snapshot_id}".encode()).hexdigest()
        return self.root / f"{key}.json"
