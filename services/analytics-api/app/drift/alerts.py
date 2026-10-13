"""Alert delivery and runbook lookup for drift (ADS-058). Delivery is advisory and never acts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from packages.platform_contracts.drift import DriftAlert, DriftReport

RUNBOOK_DIR = Path(__file__).resolve().parents[4] / "docs" / "execution" / "enterprise-analytics" / "runbooks"
REQUIRED_RUNBOOK_SECTIONS = ("## Symptom", "## Likely causes", "## Read-only checks", "## Mitigation", "## Do not")


class AlertSink(Protocol):
    def emit(self, alert: DriftAlert, report: DriftReport) -> None: ...


class InMemoryAlertSink:
    def __init__(self) -> None:
        self.alerts: list[DriftAlert] = []

    def emit(self, alert: DriftAlert, report: DriftReport) -> None:
        self.alerts.append(alert)


def runbook_path(runbook_id: str, root: Path = RUNBOOK_DIR) -> Path:
    return root / f"{runbook_id}.md"


def runbook_problems(runbook_id: str, root: Path = RUNBOOK_DIR) -> list[str]:
    path = runbook_path(runbook_id, root)
    if not path.is_file():
        return [f"{runbook_id}: runbook file is missing"]
    body = path.read_text()
    return [
        f"{runbook_id}: missing section {section!r}" for section in REQUIRED_RUNBOOK_SECTIONS if section not in body
    ]


def deliver(report: DriftReport, sink: AlertSink) -> DriftReport:
    for alert in report.alerts:
        sink.emit(alert, report)
    return report
