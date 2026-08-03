from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Optional

from src.quant_data.config import get_quant_config, QuantDataConfig
from src.quant_data.tushare_downloader import TushareDownloader
from src.quant_data.types import DownloadResult

logger = logging.getLogger(__name__)


class QuantDataScheduler:
    """Daily incremental data pull scheduler.

    Runs after market close (~18:00 CST) to pull Tushare data.
    """

    def __init__(self, config: Optional[QuantDataConfig] = None) -> None:
        self._config = config or get_quant_config()
        self._downloader = TushareDownloader(self._config)

    def run_daily(self, trade_date: Optional[str] = None) -> Dict[str, DownloadResult]:
        """Execute daily incremental pull."""
        logger.info("Starting daily pull for %s", trade_date or "today")
        results = self._downloader.pull_daily_incremental(trade_date=trade_date)
        for name, result in results.items():
            logger.info("  %s: %s (%d rows)", name, result.status.value, result.rows_fetched)
        return results

    def run_loop(self, schedule_time: str = "18:30") -> None:
        """Run as a long-running process with schedule library."""
        import schedule as sched
        logger.info("Scheduling daily pull at %s", schedule_time)
        sched.every().day.at(schedule_time).do(self.run_daily)
        import time
        while True:
            sched.run_pending()
            time.sleep(60)
