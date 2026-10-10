"""Generate dbt docs and test change proposals from triage records (ADS-053).

The generator reads the certified contract and the approved dbt schema files, and writes only to the
proposal tables. It never edits a dbt file, never imports a process-spawning module, and never runs dbt:
the validation commands are text on the proposal for a reviewer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.proposals.dbt_project import (
    DbtProject,
    DbtProjectError,
    canonical,
    find_column,
    has_test,
    render_edit,
    unified_diff,
)
from app.proposals.dbt_rules import DBT_RULES_VERSION, DbtFacts, DbtSpec, NoDbtProposal, decide_dbt
from app.proposals.service import GenerationResult, ProposalError, ProposalService
from packages.platform_contracts.proposals import ChangeProposal, DbtEdit, proposal_fingerprint


class DbtProposalService(ProposalService):
    def __init__(self, *args: Any, project: DbtProject, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.project = project

    def generate_dbt(self, triage_id: str, *, tenant_id: str) -> GenerationResult:
        record, feedback, envelope, state = self._inputs(triage_id, tenant_id)
        early = decide_dbt(DbtFacts(record.category, record.rule_id, record.basis_kind, model="_"))
        if isinstance(early, NoDbtProposal) and early.reason in {"claim_only", "category_not_applicable"}:
            return GenerationResult(None, early.reason)
        document = self._certified(envelope)
        facts = self._facts(record, feedback, envelope, state, document)
        decision = decide_dbt(facts)
        if isinstance(decision, NoDbtProposal):
            return GenerationResult(None, decision.reason)
        return self._propose(decision, record, envelope.semantic_contract or "")

    # ---- internals ----

    def _facts(self, record: Any, feedback: Any, envelope: Any, state: Any, document: Any) -> DbtFacts:
        contract = document.contract
        ref = envelope.semantic_contract or ""
        fields = {f.id: f for f in contract.fields}
        datasets = {d.id: d for d in contract.datasets}
        intent_metrics = [m["metric_id"] for m in (state.intent or {}).get("metrics", [])]
        metric = next((m for m in contract.metrics if m.id in intent_metrics), None)
        model = column = description = None
        correction = feedback.correction.semantic_id if feedback.correction else None
        if correction:
            target = next((m for m in contract.metrics if m.id == correction), None)
            kind = "metric"
            if target is None:
                target = next((d for d in contract.dimensions if d.id == correction), None)
                kind = "dimension"
            field = None
            if target is not None:
                field_id = target.measure_field_id if kind == "metric" else target.field_id
                field = fields.get(field_id) if field_id else None
                if field is not None:
                    detail = f"({target.aggregation})" if kind == "metric" else f"({target.dimension_type})"
                    description = f"{kind.capitalize()} '{target.id}' {detail}; defined in semantic contract {ref}."
            elif correction in fields:
                field, kind = fields[correction], "field"
                description = f"Field '{field.id}' ({field.data_type}); defined in semantic contract {ref}."
            if field is not None:
                column = field.physical_name
                model = datasets[field.dataset_id].physical_name
        key_columns: tuple[str, ...] = ()
        measure_column = None
        if metric is not None:
            model = model or datasets[metric.dataset_id].physical_name
            key_columns = tuple(fields[k].physical_name for k in metric.grain.key_field_ids if k in fields)
            if metric.measure_field_id in fields:
                measure_column = fields[metric.measure_field_id].physical_name
        return DbtFacts(
            triage_category=record.category,
            triage_rule_id=record.rule_id,
            basis_kind=record.basis_kind,
            issue_codes=tuple(envelope.result.issue_codes) if envelope.result else (),
            model=model,
            correction_column=column,
            correction_description=description,
            key_columns=key_columns,
            measure_column=measure_column,
        )

    def _propose(self, spec: DbtSpec, record: Any, contract_ref: str) -> GenerationResult:
        location = self.project.locate_model(spec.model)
        if location is None:
            return GenerationResult(None, "model_not_found_in_approved_files")
        column = find_column(location.document, spec.model, spec.column)
        if column is None:
            return GenerationResult(None, "column_not_found")
        if spec.edit == "description" and column.get("description"):
            return GenerationResult(None, "column_already_described")
        if spec.edit == "test" and has_test(column, spec.test_name or ""):
            return GenerationResult(None, "column_already_tested")
        try:
            after = render_edit(
                location.text, spec.model, spec.column, description=spec.description, test_name=spec.test_name
            )
        except DbtProjectError:
            return GenerationResult(None, "column_not_found")
        diff = unified_diff(location.file_path, canonical(location.text), after)
        file_fingerprint = hashlib.sha256(location.text.encode()).hexdigest()
        edit = DbtEdit(
            file_path=location.file_path,
            model=spec.model,
            column=spec.column,
            edit=spec.edit,
            description=spec.description,
            test_name=spec.test_name,
        )
        target_id = f"{spec.model}.{spec.column}"
        parameters = {"edit": spec.edit, **({"test": spec.test_name} if spec.test_name else {})}
        base = f"dbt:{location.file_path}"
        fingerprint = proposal_fingerprint(
            kind="dbt",
            operation=spec.operation,
            target_kind="dbt_column",
            target_id=target_id,
            parameters=parameters,
            base_contract=base,
            base_contract_fingerprint=file_fingerprint,
            rules_version=DBT_RULES_VERSION,
        )
        fields = dict(
            proposal_id=fingerprint[:32],
            tenant_id=record.tenant_id,
            kind="dbt",
            operation=spec.operation,
            target_kind="dbt_column",
            target_id=target_id,
            parameters=parameters,
            base_contract=base,
            base_contract_fingerprint=file_fingerprint,
            dbt_edit=edit,
            unified_diff=diff,
            validation_commands=("dbt parse", f"dbt test --select {spec.model}"),
            patch_note="Review and apply with dbt tooling; the diff is against the PyYAML-canonical form of the file.",
            rationale_codes=spec.rationale_codes + (f"rule:{spec.rule_id}", f"contract:{contract_ref}"),
            origin_triage_id=record.triage_id,
            origin_feedback_id=record.feedback_id,
            origin_run_id=record.run_id,
            rules_version=DBT_RULES_VERSION,
            created_at=self.now(),
        )
        draft = ChangeProposal(**fields, content_fingerprint="0" * 64)
        excluded = {"content_fingerprint", "created_at", "origin_triage_id", "origin_feedback_id", "origin_run_id"}
        content = {k: v for k, v in draft.model_dump(mode="json").items() if k not in excluded}
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        proposal = ChangeProposal(**fields, content_fingerprint=digest)
        created, linked = self.store.append(proposal, triage_id=record.triage_id, feedback_id=record.feedback_id)
        return GenerationResult(self.store.get(proposal.proposal_id, tenant_id=record.tenant_id), None, created, linked)


__all__ = ["DbtProposalService", "ProposalError"]
