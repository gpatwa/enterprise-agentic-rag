from __future__ import annotations

import math

import pytest

from app.retrieval.two_tower import (
    AnnExport,
    ItemTowerInput,
    Tower,
    TwoTowerBaseline,
    TwoTowerSpec,
    UserTowerInput,
)


def test_user_and_item_vectors_are_deterministic_and_versioned() -> None:
    baseline = TwoTowerBaseline(TwoTowerSpec(model_version="demo-v1", dimensions=8))
    user = UserTowerInput(tenant_id="tenant-a", user_id="user-1", feature_tokens=("genre:obby", "device:mobile"))
    item = ItemTowerInput(tenant_id="tenant-a", item_id="experience-1", feature_tokens=("genre:obby",))

    first = baseline.user_vector(user)
    second = baseline.user_vector(user)
    item_vector = baseline.item_vector(item)

    assert first == second
    assert first.tower is Tower.USER
    assert item_vector.tower is Tower.ITEM
    assert first.model_version == "demo-v1"
    assert len(first.values) == 8
    assert math.isclose(math.sqrt(sum(value * value for value in first.values)), 1.0, rel_tol=1e-9)


def test_empty_features_produce_stable_cold_start_vectors() -> None:
    baseline = TwoTowerBaseline(TwoTowerSpec(dimensions=16))
    value = ItemTowerInput(tenant_id="tenant-a", item_id="new-experience")

    vector = baseline.item_vector(value)

    assert vector.cold_start is True
    assert vector.values == baseline.item_vector(value).values
    assert any(vector.values)


def test_export_is_sorted_and_checksum_is_reproducible() -> None:
    baseline = TwoTowerBaseline(TwoTowerSpec(model_version="demo-v1", dimensions=4))
    values = (
        ItemTowerInput(tenant_id="tenant-a", item_id="item-2", feature_tokens=("theme:space",)),
        ItemTowerInput(tenant_id="tenant-a", item_id="item-1", feature_tokens=("theme:music",)),
    )

    export = baseline.export_items(reversed(values))
    repeat = baseline.export_items(values)

    assert isinstance(export, AnnExport)
    assert tuple(item.subject_id for item in export.vectors) == ("item-1", "item-2")
    assert export == repeat
    assert len(export.checksum) == 64


def test_contract_rejects_mismatched_export_checksum() -> None:
    baseline = TwoTowerBaseline(TwoTowerSpec(dimensions=4))
    export = baseline.export_items((ItemTowerInput(tenant_id="tenant-a", item_id="item-1"),))

    with pytest.raises(ValueError, match="checksum"):
        AnnExport(
            model_version=export.model_version,
            dimensions=export.dimensions,
            vectors=export.vectors,
            checksum="0" * 64,
        )

