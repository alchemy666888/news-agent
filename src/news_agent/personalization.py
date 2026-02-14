from __future__ import annotations

from collections import defaultdict


class PersonalizationModel:
    """Lightweight feedback loop for category weighting."""

    def __init__(self) -> None:
        self._engaged: dict[str, int] = defaultdict(int)
        self._dismissed: dict[str, int] = defaultdict(int)

    def record_engagement(self, category: str) -> None:
        self._engaged[category] += 1

    def record_dismissal(self, category: str) -> None:
        self._dismissed[category] += 1

    def weight_for(self, category: str) -> float:
        engaged = self._engaged[category]
        dismissed = self._dismissed[category]
        if engaged == 0 and dismissed == 0:
            return 1.0
        raw = 1 + ((engaged - dismissed) / max(engaged + dismissed, 1)) * 0.5
        return max(0.6, min(1.4, raw))
