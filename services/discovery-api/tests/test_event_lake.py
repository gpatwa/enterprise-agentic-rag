from datetime import datetime, timezone

import pytest

from app.domain.models import ConsentState
from app.event_lake.writer import EventLakeWriter
from app.events.models import EventType, ImpressionPayload, InteractionEvent
from packages.platform_contracts.discovery import (
    DiscoveryComponentVersion,
    DiscoveryRequestContext,
    ImpressionToken,
)


def _event(event_id: str, *, tenant_id: str = "tenant-a", synthetic: bool = True) -> InteractionEvent:
    occurred_at = datetime(2026, 2, 3, 12, 0, tzinfo=timezone.utc)
    context = DiscoveryRequestContext(
        tenant_id=tenant_id,
        principal_id="user-1",
        request_id="request-1",
        purpose="search",
        locale="en-US",
        device="web",
    )
    token = ImpressionToken.for_context(
        context,
        token_id=f"token-{event_id}",
        issued_at=occurred_at,
        expires_at=datetime(2026, 2, 3, 13, 0, tzinfo=timezone.utc),
        schema_version="v1",
        components=(
            DiscoveryComponentVersion(
                component_type="artifact",
                name="test",
                version="v1",
                digest="a" * 64,
            ),
        ),
    )
    return InteractionEvent(
        event_id=event_id,
        event_type=EventType.IMPRESSION,
        tenant_id=tenant_id,
        user_id="user-1",
        experience_id="experience-1",
        request_id="request-1",
        occurred_at=occurred_at,
        synthetic=synthetic,
        consent_state=ConsentState.PERSONALIZATION_ALLOWED,
        impression_token=token,
        payload=ImpressionPayload(position=0, surface="search", source="test", result_set_id="results-1"),
    )


def test_append_partitions_writes_manifest_and_reads_back(tmp_path):
    writer = EventLakeWriter(tmp_path)
    manifest = writer.append([_event("event-b"), _event("event-a")], manifest_id="batch-1")

    assert manifest.schema_version == "v1"
    assert manifest.event_count == 2
    assert len(manifest.partitions) == 1
    partition = manifest.partitions[0]
    assert partition.path == "events/tenant=tenant-a/date=2026-02-03/event_type=impression/events.jsonl"
    assert writer.read_partition(partition.path) == (_event("event-a"), _event("event-b"))
    assert writer.read_manifest(manifest.path).checksum_sha256 == manifest.checksum_sha256


def test_replay_is_idempotent_and_conflicting_duplicate_is_rejected(tmp_path):
    writer = EventLakeWriter(tmp_path)
    event = _event("event-a")
    first = writer.append([event], manifest_id="first")
    replay = writer.append([event], manifest_id="replay")

    assert first.event_count == 1
    assert replay.event_count == 0
    assert len(writer.read_partition(first.partitions[0].path)) == 1

    with pytest.raises(ValueError, match="different content"):
        writer.append([event.model_copy(update={"request_id": "other-request"})])


def test_rejects_non_synthetic_and_cross_tenant_batches(tmp_path):
    writer = EventLakeWriter(tmp_path)
    with pytest.raises(ValueError, match="synthetic"):
        writer.append([_event("real-event", synthetic=False)])
    with pytest.raises(ValueError, match="one tenant"):
        writer.append([_event("event-a"), _event("event-b", tenant_id="tenant-b")])


def test_read_back_is_bounded(tmp_path):
    writer = EventLakeWriter(tmp_path, max_read_events=1)
    writer.append([_event("event-a"), _event("event-b")])
    partition = "events/tenant=tenant-a/date=2026-02-03/event_type=impression/events.jsonl"

    assert len(writer.read_partition(partition)) == 1
    with pytest.raises(ValueError, match="between"):
        writer.read_partition(partition, limit=2)
