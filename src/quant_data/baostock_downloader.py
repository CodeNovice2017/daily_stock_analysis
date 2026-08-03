from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.quant_data.config import get_quant_config, QuantDataConfig
from src.quant_data.parquet_store import ParquetStore
from src.quant_data.progress import ProgressTracker
from src.quant_data.resilience import retry
from src.quant_data.stock_list import _simtrade_to_baostock, _baostock_to_simtrade

logger = logging.getLogger(__name__)

# BaoStock returns all fields as strings
MIN_KLINE_FIELDS = "date,time,open,high,low,close,volume,amount,adjustflag"

JOB_NAME = "baostock_kline_5min"


class BaostockDownloader:
    """Bulk download minute-level K-line data from BaoStock.

    Borrowed from SimTradeData: class-level session with reference counting.
    """

    _bs_logged_in: bool = False
    _bs_login_count: int = 0

    def __init__(self, config: Optional[QuantDataConfig] = None) -> None:
        self._config = config or get_quant_config()
        self._store = ParquetStore(self._config)
        self._progress = ProgressTracker(
            str(
                __import__("pathlib").Path(self._config.quant_data_dir) / "_progress"
            )
        )
        self._frequency = self._config.quant_bs_frequency

    def download_all(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        resume: bool = True,
    ) -> Dict[str, int]:
        """Download minute data for all (or specified) A-shares.

        Returns dict: symbol -> rows written.
        """
        if symbols is None:
            from src.quant_data.stock_list import get_a_share_list
            symbols = get_a_share_list()

        start = start_date or self._config.quant_bs_start_date
        end = end_date or datetime.now().strftime("%Y-%m-%d")
        years = self._split_into_years(start, end)

        logger.info(
            "Starting BaoStock download: %d stocks, %d years, freq=%s",
            len(symbols), len(years), self._frequency,
        )

        results: Dict[str, int] = {}
        batch_size = self._config.quant_bs_batch_size
        sleep_between = self._config.quant_bs_sleep_between

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            logger.info("Batch %d/%d: %d stocks", i // batch_size + 1,
                        (len(symbols) - 1) // batch_size + 1, len(batch))

            self._ensure_login()
            try:
                for symbol in batch:
                    rows = self._download_symbol(symbol, years, resume)
                    results[symbol] = rows
                    if sleep_between > 0:
                        time.sleep(sleep_between)
            except Exception:
                logger.exception("Batch failed")
            finally:
                self._maybe_logout()

        total = sum(results.values())
        logger.info("Download complete: %d stocks, %d total rows", len(results), total)
        return results

    def download_single(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> int:
        """Download minute data for a single stock."""
        start = start_date or self._config.quant_bs_start_date
        end = end_date or datetime.now().strftime("%Y-%m-%d")
        years = self._split_into_years(start, end)

        self._ensure_login()
        try:
            return self._download_symbol(symbol, years, resume=False)
        finally:
            self._maybe_logout()

    def _download_symbol(self, symbol: str, years: List[Tuple[str, str]],
                         resume: bool) -> int:
        """Download one stock across all year ranges."""
        total_rows = 0
        for year_start, year_end in years:
            year = year_start[:4]
            if resume and self._progress.is_completed(JOB_NAME, symbol, int(year)):
                continue
            try:
                bs_code = _simtrade_to_baostock(symbol)
                df = self._fetch_minute_kline(bs_code, year_start, year_end)
                if df is not None and not df.empty:
                    df = self._normalize_kline(df, symbol)
                    self._store.write_kline_partition(
                        "kline_5min", symbol, int(year), df,
                    )
                    total_rows += len(df)
                self._progress.mark_completed(JOB_NAME, symbol, int(year),
                                              len(df) if df is not None else 0)
            except Exception as e:
                logger.warning("Failed %s/%s: %s", symbol, year, e)
                self._progress.mark_failed(JOB_NAME, symbol, int(year), str(e))
        return total_rows

    @retry(max_retries=3, base_delay=2.0)
    def _fetch_minute_kline(self, bs_code: str, start_date: str,
                            end_date: str) -> Optional[pd.DataFrame]:
        """Execute BaoStock query. All fields returned as strings."""
        import baostock as bs

        rs = bs.query_history_k_data_plus(
            bs_code,
            MIN_KLINE_FIELDS,
            start_date=start_date,
            end_date=end_date,
            frequency=self._frequency,
            adjustflag="3",  # no adjustment; we store raw + adj factor separately
        )
        if rs.error_code != "0":
            logger.warning("BaoStock error %s: %s", bs_code, rs.error_msg)
            return None

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        return pd.DataFrame(rows, columns=rs.fields)

    def _normalize_kline(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Normalize BaoStock minute data. All fields are strings."""
        # Combine date + time into datetime
        df["datetime"] = pd.to_datetime(
            df["date"] + df["time"], format="%Y-%m-%d%H%M%S",
        )
        df = df.rename(columns={"volume": "volume", "amount": "amount"})

        # Convert string fields to numeric
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float32)
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype(np.int64)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").astype(np.float64)

        # Compute pct_chg
        df["pct_chg"] = df["close"].pct_change() * 100
        df["pct_chg"] = df["pct_chg"].astype(np.float32)

        return df[["datetime", "open", "high", "low", "close",
                    "volume", "amount", "pct_chg"]]

    @staticmethod
    def _split_into_years(start_date: str, end_date: str) -> List[Tuple[str, str]]:
        """Split date range into yearly chunks."""
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        ranges = []
        current = start
        while current < end:
            year_end = min(
                datetime(current.year, 12, 31),
                end,
            )
            ranges.append((
                current.strftime("%Y-%m-%d"),
                year_end.strftime("%Y-%m-%d"),
            ))
            current = datetime(current.year + 1, 1, 1)
        return ranges

    @classmethod
    def _ensure_login(cls) -> None:
        """Borrowed from SimTradeData: class-level global session."""
        import baostock as bs
        if not cls._bs_logged_in:
            bs.login()
            cls._bs_logged_in = True
        cls._bs_login_count += 1

    @classmethod
    def _maybe_logout(cls) -> None:
        """Only logout when all users are done."""
        import baostock as bs
        cls._bs_login_count -= 1
        if cls._bs_login_count <= 0:
            bs.logout()
            cls._bs_logged_in = False
            cls._bs_login_count = 0
