from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalLevel, SignalResult


class SupportBreakSignal(BaseSignal):
    name = "support_break"
    level = SignalLevel.STRONG
    min_bars = 20
    volume_ratio_threshold = 2.0

    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        if len(df) < self.min_bars:
            return None

        lookback = df.iloc[:-1].tail(self.min_bars)
        current = df.iloc[-1]

        avg_vol = lookback["vol"].mean()
        if avg_vol == 0:
            return None
        volume_ratio = current["vol"] / avg_vol
        if volume_ratio < self.volume_ratio_threshold:
            return None

        supports = [v for v in [context.ma20, context.ma60, context.prev_low] if v > 0]
        if not supports:
            return None
        support_level = min(supports)

        if current["close"] >= support_level:
            return None

        return SignalResult(
            signal_name=self.name,
            level=self.level,
            triggered_at=datetime.now(),
            ts_code=context.ts_code,
            price=float(current["close"]),
            data={
                "support_level": round(support_level, 2),
                "volume_ratio": round(volume_ratio, 2),
                "break_pct": round(
                    (support_level - current["close"]) / support_level * 100, 2
                ),
            },
        )
