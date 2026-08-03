from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalLevel, SignalResult


class PanicDropSignal(BaseSignal):
    name = "panic_drop"
    level = SignalLevel.STRONG
    min_bars = 6
    drop_pct_threshold = 2.0
    volume_ratio_threshold = 5.0

    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        if len(df) < self.min_bars:
            return None

        lookback = df.iloc[:-1].tail(self.min_bars - 1)
        current = df.iloc[-1]

        avg_vol = lookback["vol"].mean()
        if avg_vol == 0:
            return None

        volume_ratio = current["vol"] / avg_vol
        if volume_ratio < self.volume_ratio_threshold:
            return None

        if current["open"] == 0:
            return None
        drop_pct = (current["open"] - current["close"]) / current["open"] * 100
        if drop_pct < self.drop_pct_threshold:
            return None

        return SignalResult(
            signal_name=self.name,
            level=self.level,
            triggered_at=datetime.now(),
            ts_code=context.ts_code,
            price=float(current["close"]),
            data={
                "drop_pct": round(drop_pct, 2),
                "volume_ratio": round(volume_ratio, 2),
                "open_price": float(current["open"]),
            },
        )
