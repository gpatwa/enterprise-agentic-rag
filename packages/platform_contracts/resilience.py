"""Control-store backup manifest and resilience objectives (ADS-068).

Objectives (recovery point and time, lease takeover) are operating targets chosen without production data, so the shipped file is
*proposed*; the drills measure against whatever objectives they are given.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_HEX64 = r"^[0-9a-f]{64}$"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TableBackup(_Frozen):
    rows: int = Field(ge=0)
    digest: str = Field(pattern=_HEX64)


class ControlBackupManifest(_Frozen):
    backup_id: str = Field(min_length=8, max_length=64)
    created_at: datetime
    schema_revision: str = Field(min_length=1, max_length=64)
    tables: dict[str, TableBackup]
    digest: str = Field(pattern=_HEX64)

    @property
    def object_count(self) -> int:
        return sum(table.rows for table in self.tables.values())


class ObjectivesApproval(_Frozen):
    status: Literal["proposed", "approved"]
    approved_by: str | None = None
    approved_at: str | None = None
    note: str | None = None


class ResilienceObjectives(_Frozen):
    objectives_version: str = Field(min_length=1, max_length=64)
    rpo_seconds: float = Field(gt=0)  # the most data (in time) that may be lost: the backup interval
    rto_seconds: float = Field(gt=0)  # the longest a restore may take
    lease_seconds: float = Field(gt=0)
    takeover_factor: float = Field(
        default=2.0, gt=1
    )  # a dead worker's run is resumed within lease_seconds * takeover_factor
    approval: ObjectivesApproval

    @model_validator(mode="after")
    def sane(self) -> "ResilienceObjectives":
        if self.approval.status == "approved" and not (self.approval.approved_by and self.approval.approved_at):
            raise ValueError("approved objectives record who approved them and when")
        return self
