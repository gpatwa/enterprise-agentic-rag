"""Evaluate an approved candidate against the pinned regression suites (ADS-056).

Only a candidate with an approved independent review (ADS-055) is evaluated. The evaluator selects the cases
the change can affect (targeted), runs those and the full approved suites, and records a verdict that rests
only on approved thresholds. It reads thresholds and expectations; it cannot change them, and it fails closed
if any protected file changes while it runs. It promotes nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.evaluation_gate.selection import SubjectFacts, affected, select_cases
from app.review import ReviewService
from packages.platform_contracts.candidate_evaluation import EvaluationRecord, Selection, SuiteOutcome


class EvaluationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Runners(Protocol):
    version: str

    def sandbox(self, kind: str, subject_id: str, tenant_id: str) -> dict[str, Any]: ...

    def targeted(self, case_ids: tuple[str, ...], stack_kwargs: dict[str, Any]) -> SuiteOutcome: ...

    def full(self, stack_kwargs: dict[str, Any]) -> tuple[SuiteOutcome, ...]: ...


class EvaluationStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, record: EvaluationRecord) -> tuple[EvaluationRecord, bool]:
        for _ in range(2):
            try:
                with self.engine.begin() as connection:
                    row = (
                        connection.execute(
                            text(
                                "SELECT payload FROM analytics_candidate_evaluations WHERE tenant_id=:t AND evaluation_id=:e"
                            ),
                            {"t": record.tenant_id, "e": record.evaluation_id},
                        )
                        .mappings()
                        .first()
                    )
                    if row is not None:
                        return EvaluationRecord.model_validate(_load(row["payload"])), False
                    connection.execute(
                        text("""INSERT INTO analytics_candidate_evaluations
                        (tenant_id, evaluation_id, subject_kind, subject_id, subject_fingerprint, verdict,
                         content_fingerprint, payload)
                        VALUES (:t, :e, :k, :s, :f, :v, :c, :p)"""),
                        {
                            "t": record.tenant_id,
                            "e": record.evaluation_id,
                            "k": record.subject_kind,
                            "s": record.subject_id,
                            "f": record.subject_fingerprint,
                            "v": record.verdict,
                            "c": record.content_fingerprint,
                            "p": json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                        },
                    )
                    return record, True
            except IntegrityError:
                continue
        raise EvaluationError("could_not_append")

    def for_subject(
        self, kind: str, subject_id: str, fingerprint: str, *, tenant_id: str
    ) -> tuple[EvaluationRecord, ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT payload FROM analytics_candidate_evaluations WHERE tenant_id=:t AND subject_kind=:k
                    AND subject_id=:s AND subject_fingerprint=:f ORDER BY created_at, evaluation_id"""),
                    {"t": tenant_id, "k": kind, "s": subject_id, "f": fingerprint},
                )
                .mappings()
                .all()
            )
        return tuple(EvaluationRecord.model_validate(_load(r["payload"])) for r in rows)


class EvaluationService:
    def __init__(
        self,
        store: EvaluationStore,
        reviews: ReviewService,
        index: dict[str, dict],
        runners: Runners,
        protected_paths: list[Path],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.store, self.reviews, self.index, self.runners, self.protected, self.now = (
            store,
            reviews,
            index,
            runners,
            list(protected_paths),
            now,
        )

    def evaluate(self, kind: str, subject_id: str, *, tenant_id: str) -> EvaluationRecord:
        resolver = self.reviews.resolver
        subject = resolver.resolve(kind, subject_id, tenant_id=tenant_id)
        if not self.reviews.is_approved(kind, subject_id, subject.content_fingerprint, tenant_id=tenant_id):
            raise EvaluationError("review_not_approved")
        facts = self._facts(kind, subject_id, tenant_id)
        impact = affected(facts)
        targeted_ids = select_cases(self.index, impact.areas, impact.semantic_ids)
        before = self._digest()
        evaluation_id = hashlib.sha256(
            f"{tenant_id}:{kind}:{subject_id}:{subject.content_fingerprint}:{self.runners.version}:{before}".encode()
        ).hexdigest()[:32]
        existing = [
            r
            for r in self.store.for_subject(kind, subject_id, subject.content_fingerprint, tenant_id=tenant_id)
            if r.evaluation_id == evaluation_id
        ]
        if existing:
            return existing[0]  # same content, suites, and thresholds: the answer is already recorded
        stack_kwargs = self.runners.sandbox(kind, subject_id, tenant_id)
        outcomes = (self.runners.targeted(targeted_ids, stack_kwargs), *self.runners.full(stack_kwargs))
        after = self._digest()
        reason = None
        passed = all(o.passed for o in outcomes)
        if after != before:
            passed, reason = False, "protected_file_changed"
        elif not all(o.thresholds_approved for o in outcomes):
            passed, reason = False, "unapproved_thresholds"  # a verdict may only rest on approved thresholds
        elif not passed:
            reason = "suite_failed:" + ",".join(sorted({o.suite for o in outcomes if not o.passed}))
        reasons = (impact.reason,) + (() if targeted_ids else ("no_targeted_cases",))
        selection = Selection(
            areas=impact.areas,
            semantic_ids=impact.semantic_ids,
            targeted_case_ids=targeted_ids,
            reasons=reasons,
            sandbox=impact.sandbox,
        )
        fields = dict(
            evaluation_id=evaluation_id,
            tenant_id=tenant_id,
            subject_kind=kind,
            subject_id=subject_id,
            subject_fingerprint=subject.content_fingerprint,
            selection=selection,
            outcomes=outcomes,
            verdict="passed" if passed else "failed",
            reason=reason,
            protected_digest=after,
            created_at=self.now(),
        )
        draft = EvaluationRecord(**fields, content_fingerprint="0" * 64)
        content = {
            k: v for k, v in draft.model_dump(mode="json").items() if k not in {"content_fingerprint", "created_at"}
        }
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return self.store.append(EvaluationRecord(**fields, content_fingerprint=digest))[0]

    def passed(self, kind: str, subject_id: str, fingerprint: str, *, tenant_id: str) -> bool:
        """True only if an evaluation of exactly this content passed (and its review approved it)."""
        return self.reviews.is_approved(kind, subject_id, fingerprint, tenant_id=tenant_id) and any(
            r.verdict == "passed" for r in self.store.for_subject(kind, subject_id, fingerprint, tenant_id=tenant_id)
        )

    def passing_record(
        self, kind: str, subject_id: str, fingerprint: str, *, tenant_id: str
    ) -> EvaluationRecord | None:
        """The evaluation that passed for exactly this content (and whose review approved it), or None."""
        if not self.reviews.is_approved(kind, subject_id, fingerprint, tenant_id=tenant_id):
            return None
        return next(
            (
                r
                for r in self.store.for_subject(kind, subject_id, fingerprint, tenant_id=tenant_id)
                if r.verdict == "passed"
            ),
            None,
        )

    # ---- internals ----

    def _digest(self) -> str:
        digest = hashlib.sha256()
        for path in self.protected:
            digest.update(str(path.name).encode() + (path.read_bytes() if path.exists() else b""))
        return digest.hexdigest()

    def _facts(self, kind: str, subject_id: str, tenant_id: str) -> SubjectFacts:
        resolver = self.reviews.resolver
        if kind == "change_proposal":
            proposal = resolver.proposals.get(subject_id, tenant_id=tenant_id)
            targets = (
                tuple(proposal.parameters["candidates"].split(","))
                if proposal.operation == "review_label_collision"
                else (proposal.target_id,)
            )
            if proposal.kind == "dbt":
                targets = ()
            return SubjectFacts(kind, proposal.operation, targets)
        name, _, version = subject_id.partition("@")
        if kind == "example_candidate":
            entry = resolver.registry.get("example", name, version, tenant_id=tenant_id)
            return SubjectFacts(kind, None, (entry.correction.semantic_id,) if entry.correction else ())
        return SubjectFacts(kind)


def _load(payload: Any) -> Any:
    return json.loads(payload) if isinstance(payload, str) else payload
