"""Narrow, version-pinned Apache Ossie interoperability boundary."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from packages.platform_contracts.semantic import (
    SemanticContract,
    SemanticDataset,
    SemanticDimension,
    SemanticEntity,
    SemanticField,
    SemanticGrain,
    SemanticJoin,
    SemanticMetric,
    SemanticOwner,
    SemanticRegistryDocument,
)

OSSIE_SPEC_VERSION = "0.2.0.dev0"
OSSIE_MAPPING_VERSION = "ads-008.v1"


class OssieCompatibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["import", "export"]
    ossie_spec_version: str
    ossie_schema_fingerprint: str
    mapping_version: str = OSSIE_MAPPING_VERSION
    compass_contract_version: str
    source_reference: str
    source_fingerprint: str
    tenant_id: str | None
    provenance: Literal["complete", "incomplete", "conflicting"]
    supported_paths: tuple[str, ...] = ()
    extended_paths: tuple[str, ...] = ()
    lossy_paths: tuple[str, ...] = ()
    unsupported_paths: tuple[str, ...] = ()
    round_trip: Literal["exact_subset", "extension_preserved", "lossy", "rejected"]
    certification_eligible: bool = False


def import_ossie(
    payload: dict[str, Any],
    *,
    tenant_id: str,
    source_reference: str,
    source_fingerprint: str | None = None,
) -> tuple[SemanticRegistryDocument, OssieCompatibilityReport]:
    """Import supported Ossie core constructs as a draft Compass document."""
    spec_version = str(payload.get("version", ""))
    schema_fingerprint = _fingerprint(payload)
    source_digest = source_fingerprint or schema_fingerprint
    if spec_version != OSSIE_SPEC_VERSION:
        report = _report(
            operation="import", payload=payload, source_reference=source_reference,
            source_fingerprint=source_digest, tenant_id=tenant_id, round_trip="rejected",
            unsupported=("version",), compass_version="v1",
        )
        raise ValueError(f"unsupported Ossie version: {spec_version or 'missing'}; report={report.model_dump_json()}")
    models = payload.get("semantic_model") or []
    if len(models) != 1:
        raise ValueError("ADS-011 import requires exactly one semantic_model")
    model = models[0]
    owners = _owners(model, tenant_id)
    datasets: list[SemanticDataset] = []
    fields: list[SemanticField] = []
    entities: list[SemanticEntity] = []
    dimensions: list[SemanticDimension] = []
    for raw_dataset in model.get("datasets", []):
        dataset_id = _id(raw_dataset.get("name"), "dataset")
        raw_fields = raw_dataset.get("fields", [])
        datasets.append(SemanticDataset(
            id=dataset_id, display_name=str(raw_dataset.get("label", raw_dataset.get("name", dataset_id))),
            source_asset_id=str(raw_dataset.get("source", dataset_id)),
            physical_name=_physical_name(raw_dataset.get("source", dataset_id)),
            description=str(raw_dataset.get("description", dataset_id)), owner_ids=[owners[0].id],
        ))
        key_names = raw_dataset.get("primary_key") or []
        if isinstance(key_names, str):
            key_names = [key_names]
        for raw_field in raw_fields:
            field_name = str(raw_field.get("name", ""))
            field_id = f"{dataset_id}.{_id(field_name, 'field')}"
            fields.append(SemanticField(
                id=field_id, dataset_id=dataset_id, physical_name=field_name,
                data_type=_data_type(raw_field.get("data_type", raw_field.get("type", "string"))),
                classification="internal",
            ))
            if raw_field.get("dimension", {}).get("is_time"):
                dimensions.append(SemanticDimension(
                        id=f"dimension.{dataset_id}.{_id(field_name, 'time')}", dataset_id=dataset_id,
                    field_id=field_id, dimension_type="temporal", owner_ids=[owners[0].id],
                ))
        if key_names:
            entities.append(SemanticEntity(
                id=f"entity.{dataset_id}", dataset_id=dataset_id,
                grain=SemanticGrain(kind="custom", key_field_ids=[f"{dataset_id}.{_id(name, 'field')}" for name in key_names]),
                owner_ids=[owners[0].id],
            ))
    dataset_ids = {dataset.id for dataset in datasets}
    joins: list[SemanticJoin] = []
    for index, relationship in enumerate(model.get("relationships", [])):
        source = _id(relationship.get("from"), "dataset")
        target = _id(relationship.get("to"), "dataset")
        if source not in dataset_ids or target not in dataset_ids:
            raise ValueError("Ossie relationship references an unknown dataset")
        from_columns = relationship.get("from_columns") or relationship.get("from_fields") or []
        to_columns = relationship.get("to_columns") or relationship.get("to_fields") or []
        joins.append(SemanticJoin(
            id=f"ossie.join.{index}", from_dataset_id=source, to_dataset_id=target,
            from_field_ids=[f"{source}.{_id(value, 'field')}" for value in from_columns],
            to_field_ids=[f"{target}.{_id(value, 'field')}" for value in to_columns],
            cardinality="many_to_one", approved=False,
        ))
    metrics: list[SemanticMetric] = []
    lossy: list[str] = []
    for raw_metric in model.get("metrics", []):
        expression = str(raw_metric.get("expression", raw_metric.get("type", ""))).upper()
        match = re.fullmatch(r"(SUM|AVG|COUNT|COUNT DISTINCT|MIN|MAX)\s*\(?\s*([A-Za-z0-9_.*]+)?\s*\)?", expression)
        dataset_id = _id(raw_metric.get("dataset"), "dataset")
        if not match or dataset_id not in dataset_ids:
            lossy.append(f"semantic_model.metrics.{raw_metric.get('name', 'unknown')}")
            continue
        aggregate = {"SUM": "sum", "AVG": "average", "COUNT": "count", "COUNT DISTINCT": "count_distinct", "MIN": "min", "MAX": "max"}[match.group(1)]
        field_name = match.group(2)
        measure = None if aggregate == "count" and field_name in {None, "*"} else f"{dataset_id}.{_id(field_name, 'field')}"
        metrics.append(SemanticMetric(
            id=_id(raw_metric.get("name"), "metric"), dataset_id=dataset_id, aggregation=aggregate,
            measure_field_id=measure, grain=SemanticGrain(kind="row", key_field_ids=[fields[0].id]),
            owner_ids=[owners[0].id], certification="candidate",
        ))
    contract = SemanticContract(
        id=_id(model.get("name"), "model"), tenant_id=tenant_id, domain=str(model.get("name", "ossie")),
        version=f"ossie-{spec_version}", owners=owners, datasets=datasets, fields=fields,
        entities=entities, dimensions=dimensions, metrics=metrics, joins=joins,
        metadata={"ossie_spec_version": spec_version, "ossie_source_reference": source_reference},
    )
    report = _report(
        operation="import", payload=payload, source_reference=source_reference,
        source_fingerprint=source_digest, tenant_id=tenant_id, round_trip="lossy" if lossy else "exact_subset",
        supported=tuple(["semantic_model.datasets", "semantic_model.datasets.fields"] if datasets else []),
        lossy=tuple(lossy), compass_version=contract.version,
    )
    return SemanticRegistryDocument(lifecycle="draft", contract=contract), report


def export_ossie(
    document: SemanticRegistryDocument,
    *,
    source_reference: str = "compass://semantic-registry",
    include_extensions: bool = True,
) -> tuple[dict[str, Any], OssieCompatibilityReport]:
    """Export the portable subset without exporting permissions or credentials."""
    contract = document.contract
    datasets: list[dict[str, Any]] = []
    for dataset in contract.datasets:
        field_rows = [
            {"name": field.physical_name, "data_type": field.data_type}
            for field in contract.fields if field.dataset_id == dataset.id
        ]
        entity = next((item for item in contract.entities if item.dataset_id == dataset.id), None)
        datasets.append({
            "name": dataset.id, "source": dataset.physical_name, "description": dataset.description,
            "fields": field_rows,
            "primary_key": [next(field.physical_name for field in contract.fields if field.id == key) for key in entity.grain.key_field_ids] if entity else [],
        })
    payload: dict[str, Any] = {
        "version": OSSIE_SPEC_VERSION,
        "semantic_model": [{"name": contract.id, "description": contract.domain, "datasets": datasets}],
    }
    if include_extensions:
        payload["semantic_model"][0]["custom_extensions"] = {
            "compass": {"contract_version": contract.version, "tenant_id": contract.tenant_id, "lifecycle": document.lifecycle}
        }
    report = _report(
        operation="export", payload=payload, source_reference=source_reference,
        source_fingerprint=_fingerprint(payload), tenant_id=contract.tenant_id,
        round_trip="extension_preserved" if include_extensions else "exact_subset",
        supported=("semantic_model.datasets", "semantic_model.datasets.fields"),
        extended=("semantic_model.custom_extensions",) if include_extensions else (),
        compass_version=contract.version,
    )
    return payload, report


def _owners(model: dict[str, Any], tenant_id: str) -> list[SemanticOwner]:
    raw_owner = model.get("owner") or model.get("owners", [{}])[0]
    owner_id = str(raw_owner.get("id", raw_owner.get("name", f"ossie.{tenant_id}")))
    return [SemanticOwner(id=_id(owner_id, "owner"), display_name=owner_id, owner_type="team")]


def _id(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_.-]", "_", text)


def _physical_name(value: Any) -> str:
    text = str(value or "dataset")
    return text.rsplit(".", 1)[-1].replace('"', "")


def _data_type(value: Any) -> str:
    value = str(value).lower()
    return value if value in {"string", "integer", "decimal", "boolean", "date", "timestamp"} else "string"


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _report(*, operation: Literal["import", "export"], payload: dict[str, Any], source_reference: str,
            source_fingerprint: str, tenant_id: str | None, round_trip: Literal["exact_subset", "extension_preserved", "lossy", "rejected"],
            compass_version: str, supported: tuple[str, ...] = (), extended: tuple[str, ...] = (),
            lossy: tuple[str, ...] = (), unsupported: tuple[str, ...] = ()) -> OssieCompatibilityReport:
    return OssieCompatibilityReport(
        operation=operation, ossie_spec_version=str(payload.get("version", OSSIE_SPEC_VERSION)),
        ossie_schema_fingerprint=_fingerprint(payload), compass_contract_version=compass_version,
        source_reference=source_reference, source_fingerprint=source_fingerprint, tenant_id=tenant_id,
        provenance="complete" if tenant_id else "incomplete", supported_paths=supported,
        extended_paths=extended, lossy_paths=lossy, unsupported_paths=unsupported,
        round_trip=round_trip, certification_eligible=False,
    )
