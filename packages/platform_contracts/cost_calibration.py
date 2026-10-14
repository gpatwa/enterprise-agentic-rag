"""Cost-unit calibration contracts (M7-H4).

Gateway cost units are uncalibrated and differ by dialect and query (25 to 263 on the reference mix). A calibration maps a dialect's raw
estimate to a stated real unit using samples measured on the real warehouse. It is a PROPOSAL until a person approves it, and an unapproved
calibration is never applied.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CostSample(_Frozen):
    dialect: str = Field(min_length=1, max_length=40)
    estimated_units: float = Field(gt=0)
    observed: float = Field(gt=0)  # in the calibration's unit, measured on the warehouse the calibration is for


class DialectFit(_Frozen):
    scale: float = Field(gt=0)
    offset: float = 0.0
    samples: int = Field(ge=2)
    r_squared: float = Field(ge=0, le=1)


class CalibrationApproval(_Frozen):
    status: Literal["proposed", "approved"] = "proposed"
    approved_by: str | None = None
    approved_at: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _approved_needs_a_person(self) -> "CalibrationApproval":
        if self.status == "approved" and not (self.approved_by and self.approved_at):
            raise ValueError("an approved calibration must say who approved it and when")
        return self


class CostCalibration(_Frozen):
    calibration_version: str = Field(min_length=1, max_length=80)
    unit: str = Field(min_length=1, max_length=80)  # what a calibrated unit is, for example "warehouse milliseconds"
    calibrated_against: str = Field(min_length=1, max_length=255)  # the system the samples came from
    valid_for_production: bool
    fits: dict[str, DialectFit]
    approval: CalibrationApproval = CalibrationApproval()
