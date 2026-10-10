from packages.platform_contracts.aiops import ValidatedCorrection


class CorrectionMemory:
    def __init__(self):
        self._items: dict[str, ValidatedCorrection] = {}

    def add(self, correction: ValidatedCorrection) -> None:
        if correction.correction_id in self._items:
            raise ValueError("correction already exists")
        self._items[correction.correction_id] = correction

    def get_for_regression(self, regression_case_id: str) -> list[ValidatedCorrection]:
        return [item for item in self._items.values() if item.regression_case_id == regression_case_id]
