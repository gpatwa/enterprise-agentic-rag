"""Append-only prompt and example registry (ADS-054).

Nothing in the runtime reads this registry; it only records what exists and refuses to let a released
version change. A released version can be created only through `register_baseline`, a candidate only
through `register_candidate` (its version is derived from its content, so it cannot collide with a
released one), and a row is never updated or deleted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from packages.platform_contracts.prompt_registry import (
    ExampleCandidate,
    PromptTemplate,
    candidate_version,
    content_fingerprint,
    text_fingerprint,
)

Entry = PromptTemplate | ExampleCandidate


class RegistryError(RuntimeError):
    pass


class RegistryConflictError(RegistryError):
    """A different entry already exists under this key; released versions never change."""


class RegistryNotFoundError(RegistryError):
    pass


class PromptRegistry:
    def __init__(self, engine: Engine, *, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.engine, self.now = engine, now

    # ---- writes ----

    def register_baseline(
        self, name: str, version: str, template_text: str, placeholders: tuple[str, ...]
    ) -> PromptTemplate:
        """Create a released system version. Re-registering identical content is a no-op; different content conflicts."""
        entry = self._prompt(
            name, version, "released", "system", None, template_text, placeholders, None, (), "system:baseline"
        )
        stored, _ = self._append(entry)
        return stored  # type: ignore[return-value]

    def register_candidate(
        self,
        *,
        name: str,
        parent_version: str,
        template_text: str,
        placeholders: tuple[str, ...],
        tenant_id: str | None = None,
        origin_triage_ids: tuple[str, ...] = (),
    ) -> tuple[PromptTemplate, bool]:
        """Register a candidate prompt for a name that has a released baseline. Returns (entry, created)."""
        if not self.versions("prompt", name, tenant_id=tenant_id, status="released"):
            raise RegistryError("a candidate needs a released baseline for its prompt name")
        parent = self.get("prompt", name, parent_version, tenant_id=tenant_id)
        if set(placeholders) != set(parent.placeholders):  # type: ignore[union-attr]
            raise RegistryError("a candidate must use the same placeholders as its parent")
        if text_fingerprint(template_text) == parent.text_fingerprint:  # type: ignore[union-attr]
            raise RegistryError("a candidate must differ from its parent")
        scope = "tenant" if tenant_id else "system"
        version = candidate_version(text_fingerprint(template_text))
        entry = self._prompt(
            name,
            version,
            "candidate",
            scope,
            tenant_id,
            template_text,
            placeholders,
            parent_version,
            origin_triage_ids,
            "system:candidate",
        )
        stored, created = self._append(entry)
        return stored, created  # type: ignore[return-value]

    def register_example(self, example: ExampleCandidate) -> tuple[ExampleCandidate, bool]:
        stored, created = self._append(example)
        return stored, created  # type: ignore[return-value]

    # ---- reads ----

    def get(self, kind: str, name: str, version: str, *, tenant_id: str | None = None) -> Entry:
        """A system entry, or the caller's own tenant entry. Another tenant's entry is never visible."""
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT payload FROM analytics_prompt_registry
                    WHERE kind=:k AND name=:n AND version=:v AND (scope='system' OR (scope='tenant' AND tenant_id=:t))"""),
                    {"k": kind, "n": name, "v": version, "t": tenant_id or "\0"},
                )
                .mappings()
                .all()
            )
        if not rows:
            raise RegistryNotFoundError("no such version visible to this tenant")
        return _load(kind, rows[0]["payload"])

    def versions(
        self, kind: str, name: str, *, tenant_id: str | None = None, status: str | None = None
    ) -> list[tuple[str, str, str]]:
        """(version, status, scope) of the entries the tenant can see, oldest first."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("""SELECT version, status, scope FROM analytics_prompt_registry
                WHERE kind=:k AND name=:n AND (scope='system' OR (scope='tenant' AND tenant_id=:t))
                ORDER BY created_at, version"""),
                {"k": kind, "n": name, "t": tenant_id or "\0"},
            ).all()
        return [(v, s, sc) for v, s, sc in rows if status is None or s == status]

    # ---- internals ----

    def _prompt(
        self, name, version, status, scope, tenant_id, template_text, placeholders, parent, triage_ids, created_by
    ) -> PromptTemplate:
        fields = dict(
            name=name,
            version=version,
            status=status,
            scope=scope,
            tenant_id=tenant_id,
            template_text=template_text,
            placeholders=tuple(sorted(placeholders)),
            text_fingerprint=text_fingerprint(template_text),
            parent_version=parent,
            origin_triage_ids=tuple(triage_ids),
            created_by=created_by,
            created_at=self.now(),
        )
        draft = PromptTemplate(**fields, content_fingerprint="0" * 64)
        return PromptTemplate(**fields, content_fingerprint=content_fingerprint(draft))

    def _append(self, entry: Entry) -> tuple[Entry, bool]:
        tenant = entry.tenant_id or ""
        key = {"s": entry.scope, "t": tenant, "k": entry.kind, "n": entry.name, "v": entry.version}
        for _ in range(2):
            try:
                with self.engine.begin() as connection:
                    row = (
                        connection.execute(
                            text("""SELECT payload, content_fingerprint FROM analytics_prompt_registry
                            WHERE scope=:s AND tenant_id=:t AND kind=:k AND name=:n AND version=:v"""),
                            key,
                        )
                        .mappings()
                        .first()
                    )
                    if row is not None:
                        if row["content_fingerprint"] != entry.content_fingerprint:
                            raise RegistryConflictError("this version already exists with different content")
                        return _load(entry.kind, row["payload"]), False
                    connection.execute(
                        text("""INSERT INTO analytics_prompt_registry
                        (scope, tenant_id, kind, name, version, status, content_fingerprint, payload)
                        VALUES (:s, :t, :k, :n, :v, :status, :fp, :payload)"""),
                        {
                            **key,
                            "status": entry.status,
                            "fp": entry.content_fingerprint,
                            "payload": json.dumps(entry.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                        },
                    )
                    return entry, True
            except IntegrityError:
                continue
        raise RegistryError("could not append to the registry after repeated contention")


def _load(kind: str, payload: Any) -> Entry:
    data = json.loads(payload) if isinstance(payload, str) else payload
    return PromptTemplate.model_validate(data) if kind == "prompt" else ExampleCandidate.model_validate(data)
