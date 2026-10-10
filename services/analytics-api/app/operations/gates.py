from packages.platform_contracts.operations import AlertDecision, BackupManifest


def evaluate_alert(name: str, value: float, target: float, *, higher_is_bad: bool, severity: str = "warning") -> AlertDecision:
    firing = value >= target if higher_is_bad else value < target
    return AlertDecision(name=name, value=value, target=target, firing=firing, severity=severity)


def validate_backup(manifest: BackupManifest, expected_control_store: str, minimum_objects: int = 1) -> None:
    if manifest.control_store != expected_control_store:
        raise ValueError("backup is for the wrong control store")
    if manifest.object_count < minimum_objects:
        raise ValueError("backup contains too few objects")
