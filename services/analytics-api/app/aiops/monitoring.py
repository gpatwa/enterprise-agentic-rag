from packages.platform_contracts.aiops import DriftSignal


class DriftMonitor:
    def observe(self, signal_type: str, tenant_id: str, value: float, threshold: float) -> DriftSignal:
        return DriftSignal(signal_type=signal_type, tenant_id=tenant_id, value=value, threshold=threshold, alert=value >= threshold)
