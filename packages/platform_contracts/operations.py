"""Operational SLO, retention, backup, and release-drill contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class SLOTarget(BaseModel):
    name: Literal["availability", "p95_latency_ms", "error_rate", "evaluation_pass_rate", "cost_per_query"]
    target: float = Field(ge=0)
    window: Literal["5m", "1h", "24h", "7d", "30d"]
    runbook: str = Field(min_length=1, max_length=512)


class AlertDecision(BaseModel):
    name: str
    value: float = Field(ge=0)
    target: float = Field(ge=0)
    firing: bool
    severity: Literal["info", "warning", "critical"]


class RetentionPolicy(BaseModel):
    evidence_days: int = Field(ge=1)
    audit_days: int = Field(ge=1)
    deletion_mode: Literal["scheduled", "customer_triggered"]
    residency: str = Field(min_length=1, max_length=100)


class BackupManifest(BaseModel):
    backup_id: str
    control_store: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    object_count: int = Field(ge=0)
    digest: str = Field(min_length=64, max_length=64)


class DrillResult(BaseModel):
    drill: Literal["restore", "rollback", "failover", "rotation"]
    passed: bool
    duration_seconds: float = Field(ge=0)
    findings: list[str] = Field(default_factory=list)
