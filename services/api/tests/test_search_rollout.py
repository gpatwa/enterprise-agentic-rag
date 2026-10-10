import pytest


def test_canary_assignment_is_stable_and_bounded():
    from app.search.rollout import rollout_bucket, use_opensearch

    assert rollout_bucket("tenant-acme") == rollout_bucket("tenant-acme")
    assert 0 <= rollout_bucket("tenant-acme") < 100
    assert use_opensearch("tenant-acme", canary_percent=100, enabled=True)
    assert not use_opensearch("tenant-acme", canary_percent=0, enabled=True)
    assert not use_opensearch("tenant-acme", canary_percent=100, enabled=True, rollback=True)
    with pytest.raises(ValueError):
        use_opensearch("tenant-acme", canary_percent=101, enabled=True)
