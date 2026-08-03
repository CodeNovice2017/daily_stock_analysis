from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalLevel, SignalResult


class VolumeBreakoutSignal(BaseSignal):
    name = "volume_breakout"
    level = SignalLevel.STRONG
    min_bars = 21
    volume_ratio_threshold = 3.0

    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        if len(df) < self.min_bars:
            return None

        lookback = df.iloc[:-1].tail(20)
        current = df.iloc[-1]

        avg_vol = lookback["vol"].mean()
        if avg_vol == 0:
            return None

        volume_ratio = current["vol"] / avg_vol
        if volume_ratio < self.volume_ratio_threshold:
            return None

        prev_high = lookback["high"].max()
        if current["close"] <= prev_high:
            return None

        return SignalResult(
            signal_name=self.name,
            level=self.level,
            triggered_at=datetime.now(),
            ts_code=context.ts_code,
            price=float(current["close"]),
            data={
                "volume_ratio": round(volume_ratio, 2),
                "breakout_price": round(prev_high, 2),
                "prev_high_20": round(prev_high, 2),
            },
        )
