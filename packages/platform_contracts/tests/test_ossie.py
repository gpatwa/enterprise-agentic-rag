from copy import deepcopy

import pytest

from packages.platform_contracts.ossie import export_ossie, import_ossie


@pytest.fixture
def ossie_model():
    return {
        "version": "0.2.0.dev0",
        "semantic_model": [{
            "name": "commerce",
            "owner": {"id": "team.data"},
            "datasets": [{
                "name": "orders", "source": "warehouse.orders", "description": "One row per order",
                "primary_key": ["order_id"],
                "fields": [
                    {"name": "order_id", "data_type": "string"},
                    {"name": "ordered_at", "data_type": "timestamp", "dimension": {"is_time": True}},
                    {"name": "amount", "data_type": "decimal"},
                ],
            }],
            "metrics": [{"name": "revenue", "dataset": "orders", "expression": "SUM(amount)"}],
        }],
    }


def test_ossie_import_is_draft_and_reports_supported_subset(ossie_model):
    document, report = import_ossie(
        ossie_model, tenant_id="tenant-a", source_reference="file://model.json",
    )

    assert document.lifecycle == "draft"
    assert document.contract.datasets[0].physical_name == "orders"
    assert document.contract.metrics[0].id == "revenue"
    assert document.contract.dimensions[0].dimension_type == "temporal"
    assert report.round_trip == "exact_subset"
    assert report.certification_eligible is False
    assert report.provenance == "complete"


def test_ossie_export_preserves_compass_extension_without_authority(ossie_model):
    document, _ = import_ossie(ossie_model, tenant_id="tenant-a", source_reference="fixture")
    payload, report = export_ossie(document)

    assert payload["version"] == "0.2.0.dev0"
    assert payload["semantic_model"][0]["custom_extensions"]["compass"]["tenant_id"] == "tenant-a"
    assert report.round_trip == "extension_preserved"
    assert report.certification_eligible is False


def test_ossie_unknown_version_is_rejected(ossie_model):
    invalid = deepcopy(ossie_model)
    invalid["version"] = "9.0.0"
    with pytest.raises(ValueError, match="unsupported Ossie version"):
        import_ossie(invalid, tenant_id="tenant-a", source_reference="fixture")
