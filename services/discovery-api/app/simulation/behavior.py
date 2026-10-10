"""Seedable exposure-aware behavior simulation.

This module generates fictional events for local evaluation only.  It deliberately
does not model real people, call providers, or infer actions from future events.
Each action is produced immediately after the impression that authorizes it.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import (
    ExperienceRecord,
    ImmersiveDiscoveryContext,
    Persona,
    UserProfile,
    evaluate_eligibility,
)
from app.events.models import (
    ClickPayload,
    CoPlayPayload,
    DetailViewPayload,
    EventType,
    ImpressionPayload,
    InteractionEvent,
    InteractionEventBatch,
    PlayPayload,
    PlaytimePayload,
    QualifiedPlayPayload,
    RetentionPayload,
    ReturnPayload,
)
from packages.platform_contracts.discovery import (
    DiscoveryComponentVersion,
    ImpressionToken,
)


class SimulationProfile(str, Enum):
    """Named bounds for repeatable local simulation runs."""

    DEMO = "demo"
    EVALUATION = "evaluation"


class BehaviorConfig(BaseModel):
    """Small, explicit knobs that keep simulation behavior auditable."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_exposures: int = Field(default=12, ge=1, le=100)
    max_events: int = Field(default=100, ge=1, le=500)
    qualified_play_threshold_seconds: int = Field(default=30, ge=1, le=3_600)
    retention_probability: float = Field(default=0.65, ge=0, le=1, allow_inf_nan=False)
    return_probability: float = Field(default=0.35, ge=0, le=1, allow_inf_nan=False)


_CONFIGS = {
    SimulationProfile.DEMO: BehaviorConfig(max_exposures=8, max_events=64),
    SimulationProfile.EVALUATION: BehaviorConfig(max_exposures=24, max_events=180),
}


@dataclass(frozen=True)
class BehaviorSimulation:
    """The bounded, ordered output of one simulation run."""

    events: tuple[InteractionEvent, ...]
    batch: InteractionEventBatch
    exposed_experience_ids: tuple[str, ...]


class BehaviorSimulator:
    """Generate synthetic events with strict impression lineage."""

    def __init__(
        self,
        seed: int,
        *,
        profile: SimulationProfile | str = SimulationProfile.DEMO,
        config: BehaviorConfig | None = None,
        started_at: datetime | None = None,
    ) -> None:
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise TypeError("seed must be an integer")
        self.seed = seed
        self.profile = profile if isinstance(profile, SimulationProfile) else SimulationProfile(profile)
        self.config = config or _CONFIGS[self.profile]
        self.started_at = started_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")

    def simulate(
        self,
        user: UserProfile,
        experiences: Sequence[ExperienceRecord],
        context: ImmersiveDiscoveryContext,
    ) -> BehaviorSimulation:
        """Simulate one request using only prior generated state."""
        if not user.synthetic or any(not item.synthetic for item in experiences):
            raise ValueError("behavior simulation accepts synthetic records only")
        if context.request_context.principal_id != user.user_id:
            raise ValueError("context principal must match user")
        if context.request_context.tenant_id != user.tenant_id:
            raise ValueError("context tenant must match user")

        rng = random.Random(self.seed)
        eligible = [
            item
            for item in experiences
            if evaluate_eligibility(item, user, context).eligible
        ][: self.config.max_exposures]
        events: list[InteractionEvent] = []
        for position, experience in enumerate(eligible):
            impression_time = self.started_at + timedelta(seconds=position * 10)
            token = self._token(context, position, impression_time)
            events.append(
                InteractionEvent(
                    event_id=f"sim-{self.seed}-impression-{position:03d}",
                    event_type=EventType.IMPRESSION,
                    tenant_id=user.tenant_id,
                    user_id=user.user_id,
                    experience_id=experience.experience_id,
                    request_id=context.request_context.request_id,
                    occurred_at=impression_time,
                    synthetic=True,
                    consent_state=user.consent_state,
                    impression_token=token,
                    payload=ImpressionPayload(
                        position=position,
                        surface=context.surface,
                        source="simulator",
                        result_set_id=f"sim-{self.seed}-results",
                    ),
                )
            )
            self._append_actions(events, user, experience, context, token, position, rng, impression_time)
            if len(events) >= self.config.max_events:
                break

        # Return and retention are intentionally future-dated signals.  Sort only
        # after decisions are made so the emitted batch remains chronologically valid.
        events = sorted(events, key=lambda item: (item.occurred_at, item.event_id))[: self.config.max_events]
        batch = InteractionEventBatch(batch_id=f"sim-{self.seed}-batch", events=tuple(events))
        return BehaviorSimulation(
            events=tuple(events),
            batch=batch,
            exposed_experience_ids=tuple(item.experience_id for item in eligible),
        )

    def _append_actions(
        self,
        events: list[InteractionEvent],
        user: UserProfile,
        experience: ExperienceRecord,
        context: ImmersiveDiscoveryContext,
        token: ImpressionToken,
        position: int,
        rng: random.Random,
        impression_time: datetime,
    ) -> None:
        affinity = self._affinity(user, experience, context)
        if rng.random() >= min(0.95, 0.18 + affinity * 0.62):
            return
        prefix = f"sim-{self.seed}-{position:03d}"
        action_time = impression_time + timedelta(seconds=1)
        events.append(self._event(
            f"{prefix}-click", EventType.CLICK, ClickPayload(), user, experience, context, token, action_time
        ))
        events.append(self._event(
            f"{prefix}-detail", EventType.DETAIL_VIEW,
            DetailViewPayload(entry_point=context.surface, dwell_seconds=8 + int(affinity * 20)),
            user, experience, context, token, action_time + timedelta(seconds=1),
        ))
        play_time = max(5, int(12 + affinity * 90 + rng.random() * 20))
        events.append(self._event(
            f"{prefix}-play", EventType.PLAY,
            PlayPayload(launch_source="detail", session_id=f"{prefix}-session"),
            user, experience, context, token, action_time + timedelta(seconds=2),
        ))
        events.append(self._event(
            f"{prefix}-playtime", EventType.PLAYTIME,
            PlaytimePayload(duration_seconds=play_time), user, experience, context, token,
            action_time + timedelta(seconds=3),
        ))
        if play_time >= self.config.qualified_play_threshold_seconds:
            events.append(self._event(
                f"{prefix}-qualified", EventType.QUALIFIED_PLAY,
                QualifiedPlayPayload(
                    duration_seconds=play_time,
                    qualification_threshold_seconds=self.config.qualified_play_threshold_seconds,
                ), user, experience, context, token, action_time + timedelta(seconds=4),
            ))
        if user.persona is Persona.SOCIAL or "co-play" in {item.value for item in experience.mechanics}:
            events.append(self._event(
                f"{prefix}-coplay", EventType.CO_PLAY,
                CoPlayPayload(participant_count=2, session_id=f"{prefix}-session"),
                user, experience, context, token, action_time + timedelta(seconds=5),
            ))
        if rng.random() < self.config.return_probability * max(0.5, affinity):
            events.append(self._event(
                f"{prefix}-return", EventType.RETURN,
                ReturnPayload(days_since_prior_play=1 + (position % 7)),
                user, experience, context, token, action_time + timedelta(days=1),
            ))
        events.append(self._event(
            f"{prefix}-retention", EventType.RETENTION,
            RetentionPayload(horizon="D1", retained=rng.random() < self.config.retention_probability * max(0.5, affinity)),
            user, experience, context, token, action_time + timedelta(days=1, seconds=1),
        ))

    @staticmethod
    def _affinity(user: UserProfile, experience: ExperienceRecord, context: ImmersiveDiscoveryContext) -> float:
        genre_hits = len(set(user.preferences.genres) & set(experience.genres))
        theme_hits = len(set(user.preferences.themes) & set(experience.themes))
        context_bonus = 0.1 if context.request_context.device in {item.value for item in experience.devices} else 0
        return min(1.0, 0.15 + genre_hits * 0.22 + theme_hits * 0.18 + context_bonus)

    def _token(self, context: ImmersiveDiscoveryContext, position: int, issued_at: datetime) -> ImpressionToken:
        component = DiscoveryComponentVersion(
            component_type="artifact", name="behavior-simulator", version="v1", digest="b" * 64
        )
        return ImpressionToken.for_context(
            context.request_context,
            token_id=f"sim-{self.seed}-token-{position:03d}",
            issued_at=issued_at,
            expires_at=issued_at + timedelta(minutes=5),
            schema_version="v1",
            components=(component,),
        )

    @staticmethod
    def _event(
        event_id: str,
        event_type: EventType,
        payload: object,
        user: UserProfile,
        experience: ExperienceRecord,
        context: ImmersiveDiscoveryContext,
        token: ImpressionToken,
        occurred_at: datetime,
    ) -> InteractionEvent:
        return InteractionEvent(
            event_id=event_id,
            event_type=event_type,
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            experience_id=experience.experience_id,
            request_id=context.request_context.request_id,
            occurred_at=occurred_at,
            synthetic=True,
            consent_state=user.consent_state,
            impression_token=token,
            payload=payload,
        )


def simulate_behavior(
    seed: int,
    user: UserProfile,
    experiences: Sequence[ExperienceRecord],
    context: ImmersiveDiscoveryContext,
    *,
    profile: SimulationProfile | str = SimulationProfile.DEMO,
) -> BehaviorSimulation:
    """Convenience wrapper for one bounded deterministic simulation."""
    return BehaviorSimulator(seed, profile=profile).simulate(user, experiences, context)
