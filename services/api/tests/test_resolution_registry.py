import pytest

from app.resolution.registry import RegistryEntry, ResolutionStage, empty_registry


def entry(version="v1", stage=ResolutionStage.INTENT):
    return RegistryEntry(stage, version, "prompt-1", "model-1", "policy-1", metadata={"temperature": 0})


def test_snapshot_resolves_explicit_versions_and_is_immutable():
    registry = empty_registry().register(entry())
    assert registry.resolve("intent", "v1").model_version == "model-1"
    with pytest.raises(TypeError):
        registry.entries[ResolutionStage.INTENT]["v2"] = entry("v2")
    with pytest.raises(TypeError):
        registry.resolve("intent", "v1").metadata["x"] = 1


def test_registration_is_copy_on_write_and_rollback_is_selection():
    first = empty_registry().register(entry("v1"))
    second = first.register(entry("v2"))
    assert [second.resolve("intent", version).version for version in ("v1", "v2")] == ["v1", "v2"]
    with pytest.raises(LookupError):
        first.resolve("intent", "v2")


@pytest.mark.parametrize("version", ["", " ", None, "missing"])
def test_unknown_or_blank_versions_fail_closed(version):
    registry = empty_registry().register(entry())
    with pytest.raises((ValueError, LookupError)):
        registry.resolve("intent", version)


def test_all_resolution_stages_are_supported():
    registry = empty_registry()
    for stage in ResolutionStage:
        registry = registry.register(entry(stage=stage))
    assert {registry.resolve(stage, "v1").stage for stage in ResolutionStage} == set(ResolutionStage)
