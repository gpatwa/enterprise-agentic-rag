from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.models import ExperienceRecord, UserProfile
from app.events.models import InteractionEventBatch
from app.repositories.protocols import (
    AppendReceipt,
    CatalogRepository,
    DerivedFeatureRecord,
    EventRepository,
    FeatureRepository,
    Page,
    PageRequest,
    ProfileRepository,
)


def test_page_request_is_bounded_and_cursor_based() -> None:
    page = PageRequest(limit=100, cursor="catalog:next")

    assert page.limit == 100
    assert page.cursor == "catalog:next"

    with pytest.raises(ValueError):
        PageRequest(limit=0)
    with pytest.raises(ValueError):
        PageRequest(limit=1_001)


def test_tiny_doubles_conform_to_all_repository_protocols() -> None:
    class CatalogDouble:
        def get_experience(self, tenant_id: str, experience_id: str) -> ExperienceRecord | None:
            return None

        def list_experiences(self, tenant_id: str, page: PageRequest) -> Page[ExperienceRecord]:
            return Page(())

        def put_experience(self, tenant_id: str, record: ExperienceRecord) -> None:
            return None

    class EventDouble:
        def append_events(self, tenant_id: str, batch: InteractionEventBatch) -> AppendReceipt:
            return AppendReceipt(accepted=len(batch.events), already_present=0)

        def list_events(self, tenant_id: str, user_id: str, page: PageRequest) -> Page:
            return Page(())

    class ProfileDouble:
        def get_profile(self, tenant_id: str, user_id: str) -> UserProfile | None:
            return None

        def list_profiles(self, tenant_id: str, page: PageRequest) -> Page[UserProfile]:
            return Page(())

        def put_profile(self, tenant_id: str, profile: UserProfile) -> None:
            return None

    class FeatureDouble:
        def get_features(
            self,
            tenant_id: str,
            subject_type: str,
            subject_id: str,
            feature_version: str,
        ) -> DerivedFeatureRecord | None:
            return None

        def list_features(
            self,
            tenant_id: str,
            subject_type: str,
            page: PageRequest,
            feature_version: str,
        ) -> Page[DerivedFeatureRecord]:
            return Page(())

        def put_features(self, record: DerivedFeatureRecord) -> None:
            return None

    assert isinstance(CatalogDouble(), CatalogRepository)
    assert isinstance(EventDouble(), EventRepository)
    assert isinstance(ProfileDouble(), ProfileRepository)
    assert isinstance(FeatureDouble(), FeatureRepository)


def test_derived_features_are_versioned_and_separate_from_authority() -> None:
    record = DerivedFeatureRecord(
        tenant_id="tenant-a",
        subject_type="user",
        subject_id="user-1",
        feature_version="interest-v1",
        values=(("genre:building", 0.9),),
        computed_at=datetime.now(timezone.utc),
        source_watermark="events:42",
    )

    assert record.feature_version == "interest-v1"
    assert record.subject_type == "user"
    assert not hasattr(record, "title")
