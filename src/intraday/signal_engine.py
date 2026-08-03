from __future__ import annotations

import logging
from datetime import date
from typing import List, Set, Tuple

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalResult

logger = logging.getLogger(__name__)


class SignalEngine:
    def __init__(self) -> None:
        self.signals: List[BaseSignal] = []
        self._fired_today: Set[Tuple[str, str, date]] = set()

    def register(self, signal: BaseSignal) -> None:
        self.signals.append(signal)
        logger.debug("Registered signal: %s (%s)", signal.name, signal.level.name)

    def detect(self, df: pd.DataFrame, context: SignalContext) -> List[SignalResult]:
        results: List[SignalResult] = []
        today = date.today()
        for signal in self.signals:
            dedup_key = (signal.name, context.ts_code, today)
            if dedup_key in self._fired_today:
                continue
            try:
                result = signal.detect(df, context)
            except Exception:
                logger.exception("Signal %s raised error on %s", signal.name, context.ts_code)
                continue
            if result is not None:
                self._fired_today.add(dedup_key)
                results.append(result)
                logger.info(
                    "Signal fired: %s on %s at %.2f",
                    signal.name, context.ts_code, result.price,
                )
        return results

    def reset_daily(self) -> None:
        self._fired_today.clear()
