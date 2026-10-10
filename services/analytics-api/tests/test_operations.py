"""EA-055 to EA-057 operational contract tests."""
import pytest

from app.operations import evaluate_alert, validate_backup
from packages.platform_contracts.operations import BackupManifest


def test_alert_gate_handles_latency_and_availability_direction():
    assert evaluate_alert("latency", 1200, 1000, higher_is_bad=True).firing is True
    assert evaluate_alert("availability", 0.999, 0.99, higher_is_bad=False).firing is False


def test_backup_validation_is_control_store_specific():
    manifest = BackupManifest(backup_id="b1", control_store="analytics-control", object_count=3, digest="a" * 64)
    validate_backup(manifest, "analytics-control")
    with pytest.raises(ValueError, match="wrong control store"):
        validate_backup(manifest, "warehouse")
