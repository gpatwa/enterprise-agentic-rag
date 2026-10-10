from packages.platform_contracts.aiops import RolloutState


class RolloutManager:
    def __init__(self):
        self._states: dict[str, RolloutState] = {}

    def start_canary(self, component: str, active_version: str, canary_version: str, percent: int) -> RolloutState:
        state = RolloutState(component=component, active_version=active_version, canary_version=canary_version, canary_percent=percent, rollback_version=active_version)
        self._states[component] = state
        return state

    def rollback(self, component: str) -> RolloutState:
        state = self._states[component]
        if not state.rollback_version:
            raise ValueError("no rollback version is configured")
        updated = state.model_copy(update={"active_version": state.rollback_version, "canary_version": None, "canary_percent": 0})
        self._states[component] = updated
        return updated
