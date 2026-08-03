from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from src.intraday.types import SignalContext, SignalLevel, SignalResult


class BaseSignal(ABC):
    name: str = ""
    level: SignalLevel = SignalLevel.WEAK

    @abstractmethod
    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        ...
