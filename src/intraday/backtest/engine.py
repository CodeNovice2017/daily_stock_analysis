from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Replays historical 5-min bars through signals and records trigger outcomes."""

    def __init__(self, signals: Optional[List[BaseSignal]] = None) -> None:
        self.signals = signals or []

    def run(
        self,
        df: pd.DataFrame,
        context: SignalContext,
        lookback: int = 20,
        forward_bars: Optional[List[int]] = None,
    ) -> List[Dict]:
        if forward_bars is None:
            forward_bars = [6, 12, 48]

        records: List[Dict] = []
        fired: set = set()

        for i in range(lookback, len(df)):
            window = df.iloc[: i + 1]
            current_day = str(df.iloc[i].get("trade_time", ""))[:10]

            for signal in self.signals:
                dedup_key = (signal.name, context.ts_code, current_day)
                if dedup_key in fired:
                    continue

                result = signal.detect(window, context)
                if result is None:
                    continue

                fired.add(dedup_key)
                trigger_idx = i
                trigger_price = float(df.iloc[trigger_idx]["close"])
                forward_returns: Dict[int, float] = {}
                for fwd in forward_bars:
                    fwd_idx = trigger_idx + fwd
                    if fwd_idx < len(df):
                        fwd_price = float(df.iloc[fwd_idx]["close"])
                        forward_returns[fwd] = round(
                            (fwd_price - trigger_price) / trigger_price * 100, 2
                        )

                records.append({
                    "signal_name": signal.name,
                    "trigger_idx": trigger_idx,
                    "trigger_price": trigger_price,
                    "trigger_time": str(df.iloc[trigger_idx].get("trade_time", "")),
                    "forward_returns": forward_returns,
                })

        logger.info("Backtest produced %d trigger records", len(records))
        return records
