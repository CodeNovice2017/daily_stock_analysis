from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class IntradayDataFetcher:
    """Thin wrapper around TushareFetcher for intraday data needs.

    Accepts stock codes in any format (plain number like '600519',
    ts_code like '600519.SH', etc.) and normalizes internally.
    """

    def __init__(self, tushare_fetcher=None) -> None:
        if tushare_fetcher is not None:
            self._fetcher = tushare_fetcher
        else:
            from data_provider.tushare_fetcher import TushareFetcher
            self._fetcher = TushareFetcher()

    def _to_ts_code(self, stock_code: str) -> str:
        return self._fetcher._convert_stock_code(stock_code)

    def fetch_minute_bars(
        self,
        stock_code: str,
        freq: str = "5min",
        start_date: str = "",
        end_date: str = "",
        bars: int = 0,
    ) -> Optional[pd.DataFrame]:
        ts_code = self._to_ts_code(stock_code)
        df = self._fetcher.get_minute_data(
            ts_code=ts_code, freq=freq, start_date=start_date, end_date=end_date,
        )
        if df is None or df.empty:
            return None
        if bars > 0 and len(df) > bars:
            df = df.iloc[-bars:]
        return df
