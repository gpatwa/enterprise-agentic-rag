from packages.platform_contracts.aiops import ComponentVersion


class ComponentRegistry:
    def __init__(self):
        self._versions: dict[tuple[str, str], ComponentVersion] = {}

    def register(self, version: ComponentVersion) -> ComponentVersion:
        key = (version.component, version.version)
        existing = self._versions.get(key)
        if existing and existing.immutable_digest != version.immutable_digest:
            raise ValueError("component version digest cannot change")
        self._versions[key] = version
        return version

    def resolve(self, component: str, version: str) -> ComponentVersion:
        try:
            return self._versions[(component, version)]
        except KeyError as exc:
            raise LookupError("component version was not registered") from exc
