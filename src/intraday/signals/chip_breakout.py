from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalLevel, SignalResult


class ChipBreakoutSignal(BaseSignal):
    name = "chip_breakout"
    level = SignalLevel.STRONG
    min_bars = 20
    volume_ratio_threshold = 1.5

    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        if context.chip_cost_95 <= 0:
            return None
        if len(df) < self.min_bars:
            return None

        current = df.iloc[-1]
        if current["close"] <= context.chip_cost_95:
            return None

        if context.avg_daily_volume <= 0:
            return None
        intraday_vol = df["vol"].sum()
        vol_ratio = intraday_vol / context.avg_daily_volume
        if vol_ratio < self.volume_ratio_threshold:
            return None

        return SignalResult(
            signal_name=self.name,
            level=self.level,
            triggered_at=datetime.now(),
            ts_code=context.ts_code,
            price=float(current["close"]),
            data={
                "chip_cost_95": context.chip_cost_95,
                "volume_ratio": round(vol_ratio, 2),
                "breakout_pct": round(
                    (current["close"] - context.chip_cost_95) / context.chip_cost_95 * 100, 2
                ),
            },
        )
