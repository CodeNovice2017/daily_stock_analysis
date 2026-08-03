from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from src.config import get_config as get_main_config
from src.quant_data.config import get_quant_config, QuantDataConfig
from src.quant_data.meta_store import MetaStore
from src.quant_data.parquet_store import ParquetStore
from src.quant_data.resilience import RateLimiter, retry
from src.quant_data.types import DownloadResult, DownloadStatus, DownloadTask

logger = logging.getLogger(__name__)

# Column lists (borrowed from zer0share pattern: single source of truth)
MONEYFLOW_COLS = [
    "ts_code", "trade_date", "buy_sm_vol", "buy_sm_amount",
    "sell_sm_vol", "sell_sm_amount", "buy_md_vol", "buy_md_amount",
    "sell_md_vol", "sell_md_amount", "buy_lg_vol", "buy_lg_amount",
    "sell_lg_vol", "sell_lg_amount", "buy_elg_vol", "buy_elg_amount",
    "sell_elg_vol", "sell_elg_amount", "net_mf_vol", "net_mf_amount",
]

DAILY_BASIC_COLS = [
    "ts_code", "trade_date", "close", "turnover_rate", "turnover_rate_f",
    "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm",
    "dv_ratio", "dv_ttm", "total_share", "float_share", "free_share",
    "total_mv", "circ_mv",
]

CYQ_CHIPS_COLS = [
    "ts_code", "trade_date", "price", "percent",
]


class TushareDownloader:
    """Incremental daily pull from Tushare Pro (borrowed from zer0share pattern)."""

    def __init__(self, config: Optional[QuantDataConfig] = None) -> None:
        self._config = config or get_quant_config()
        self._token = self._resolve_token()
        self._store = ParquetStore(self._config)
        self._rate_limiter = RateLimiter(
            max_calls=self._config.quant_tushare_rate_limit,
        )

    def _resolve_token(self) -> str:
        main_cfg = get_main_config()
        token = main_cfg.tushare_token
        if not token:
            raise ValueError("TUSHARE_TOKEN not configured in .env")
        return token

    def _call_tushare(self, api_name: str, **params) -> pd.DataFrame:
        """Direct HTTP call to Tushare Pro API."""
        import requests
        payload = {
            "api_name": api_name,
            "token": self._token,
            "params": params,
            "fields": "",
        }
        self._rate_limiter.acquire()
        resp = requests.post("http://api.tushare.pro", json=payload, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            logger.warning("Tushare %s error: %s", api_name, data.get("msg", ""))
            return pd.DataFrame()
        fields = data.get("data", {}).get("fields", [])
        items = data.get("data", {}).get("items", [])
        if not items:
            return pd.DataFrame(columns=fields)
        return pd.DataFrame(items, columns=fields)

    def pull_daily_incremental(
        self,
        trade_date: Optional[str] = None,
        interfaces: Optional[List[str]] = None,
    ) -> Dict[str, DownloadResult]:
        """Pull incremental data for one trading day."""
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y%m%d")

        if interfaces is None:
            interfaces = self._config.quant_tushare_interfaces.split(",")

        results = {}
        with MetaStore(self._config) as meta:
            for iface in interfaces:
                if iface == "moneyflow":
                    results["moneyflow"] = self._pull_moneyflow(trade_date)
                elif iface == "daily_basic":
                    results["daily_basic"] = self._pull_daily_basic(trade_date)
                elif iface == "cyq_chips":
                    results["cyq_chips"] = self._pull_cyq_chips(trade_date)

            # Advance watermark for successful pulls
            td = datetime.strptime(trade_date, "%Y%m%d").date()
            for name, result in results.items():
                if result.status == DownloadStatus.COMPLETED:
                    meta.update_last_date(name, td)

        return results

    def pull_backfill(
        self,
        interface: str,
        start_year: int,
        end_year: Optional[int] = None,
    ) -> int:
        """Backfill historical data year by year."""
        end_year = end_year or datetime.now().year
        total = 0
        for year in range(start_year, end_year + 1):
            logger.info("Backfilling %s for %d", interface, year)
            start = f"{year}0101"
            end = f"{year}1231"

            if interface == "moneyflow":
                df = self._call_tushare("moneyflow", start_date=start, end_date=end)
                if not df.empty:
                    cols = [c for c in MONEYFLOW_COLS if c in df.columns]
                    df = df[cols]
                    self._store.write_daily_partition(
                        f"moneyflow/{year}", start, df,
                    )
                    total += len(df)
            elif interface == "daily_basic":
                df = self._call_tushare("daily_basic", start_date=start, end_date=end,
                                        fields=",".join(DAILY_BASIC_COLS))
                if not df.empty:
                    cols = [c for c in DAILY_BASIC_COLS if c in df.columns]
                    df = df[cols]
                    self._store.write_daily_partition(
                        f"daily_basic/{year}", start, df,
                    )
                    total += len(df)

            time.sleep(0.5)

        return total

    def _pull_moneyflow(self, trade_date: str) -> DownloadResult:
        task = DownloadTask(
            symbol="ALL", start_date=trade_date, end_date=trade_date,
            frequency="daily", source="tushare", interface="moneyflow",
        )
        if self._store.partition_exists("moneyflow", trade_date=trade_date):
            return DownloadResult(task=task, status=DownloadStatus.SKIPPED)

        df = self._call_tushare("moneyflow", trade_date=trade_date)
        if df.empty:
            return DownloadResult(task=task, status=DownloadStatus.FAILED,
                                  error="No data returned")

        cols = [c for c in MONEYFLOW_COLS if c in df.columns]
        df = df[cols]
        path = self._store.write_daily_partition("moneyflow", trade_date, df)
        return DownloadResult(
            task=task, status=DownloadStatus.COMPLETED,
            rows_fetched=len(df), rows_written=len(df), file_path=path,
        )

    def _pull_daily_basic(self, trade_date: str) -> DownloadResult:
        task = DownloadTask(
            symbol="ALL", start_date=trade_date, end_date=trade_date,
            frequency="daily", source="tushare", interface="daily_basic",
        )
        if self._store.partition_exists("daily_basic", trade_date=trade_date):
            return DownloadResult(task=task, status=DownloadStatus.SKIPPED)

        df = self._call_tushare("daily_basic", trade_date=trade_date,
                                fields=",".join(DAILY_BASIC_COLS))
        if df.empty:
            return DownloadResult(task=task, status=DownloadStatus.FAILED,
                                  error="No data returned")

        cols = [c for c in DAILY_BASIC_COLS if c in df.columns]
        df = df[cols]
        path = self._store.write_daily_partition("daily_basic", trade_date, df)
        return DownloadResult(
            task=task, status=DownloadStatus.COMPLETED,
            rows_fetched=len(df), rows_written=len(df), file_path=path,
        )

    def _pull_cyq_chips(self, trade_date: str) -> DownloadResult:
        task = DownloadTask(
            symbol="ALL", start_date=trade_date, end_date=trade_date,
            frequency="daily", source="tushare", interface="cyq_chips",
        )
        if self._store.partition_exists("cyq_chips", trade_date=trade_date):
            return DownloadResult(task=task, status=DownloadStatus.SKIPPED)

        df = self._call_tushare("cyq_chips", trade_date=trade_date)
        if df.empty:
            return DownloadResult(task=task, status=DownloadStatus.FAILED,
                                  error="No data returned")

        cols = [c for c in CYQ_CHIPS_COLS if c in df.columns]
        df = df[cols]
        path = self._store.write_daily_partition("cyq_chips", trade_date, df)
        return DownloadResult(
            task=task, status=DownloadStatus.COMPLETED,
            rows_fetched=len(df), rows_written=len(df), file_path=path,
        )
