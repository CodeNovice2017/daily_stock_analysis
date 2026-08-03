from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalLevel, SignalResult


def _compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


class MacdVolumeSignal(BaseSignal):
    name = "macd_volume"
    level = SignalLevel.STRONG
    min_bars = 40
    volume_ratio_threshold = 1.5

    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        if len(df) < self.min_bars:
            return None

        dif, dea, hist = _compute_macd(df["close"])

        if hist.iloc[-2] >= 0 or hist.iloc[-1] < 0:
            return None

        if context.avg_daily_volume <= 0:
            return None
        intraday_vol = df["vol"].sum()
        vol_ratio = intraday_vol / context.avg_daily_volume
        if vol_ratio < self.volume_ratio_threshold:
            return None

        current = df.iloc[-1]
        return SignalResult(
            signal_name=self.name,
            level=self.level,
            triggered_at=datetime.now(),
            ts_code=context.ts_code,
            price=float(current["close"]),
            data={
                "dif": round(float(dif.iloc[-1]), 4),
                "dea": round(float(dea.iloc[-1]), 4),
                "macd_hist": round(float(hist.iloc[-1]), 4),
                "volume_ratio": round(vol_ratio, 2),
            },
        )
