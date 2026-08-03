from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from src.intraday.data_fetcher import IntradayDataFetcher

logger = logging.getLogger(__name__)


class BacktestDataLoader:
    """Loads historical 5-min K-line data for backtesting."""

    def __init__(self, fetcher: Optional[IntradayDataFetcher] = None, api_delay: float = 61.0) -> None:
        self._fetcher = fetcher or IntradayDataFetcher()
        self._api_delay = api_delay

    def load(self, ts_code: str, days: int = 365, freq: str = "5min") -> Optional[pd.DataFrame]:
        end_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        logger.info("Loading %d days of %s data for %s", days, freq, ts_code)
        df = self._fetcher.fetch_minute_bars(
            stock_code=ts_code, freq=freq, start_date=start_date, end_date=end_date,
        )
        if df is None or df.empty:
            logger.warning("No data returned for %s", ts_code)
            return None
        logger.info("Loaded %d bars for %s", len(df), ts_code)
        time.sleep(self._api_delay)
        return df
