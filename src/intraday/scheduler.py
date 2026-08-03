from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List, Optional

from src.intraday.data_fetcher import IntradayDataFetcher
from src.intraday.notifier import IntradayNotifier
from src.intraday.signal_engine import SignalEngine
from src.intraday.signals import ALL_SIGNALS
from src.intraday.store import IntradaySignalStore
from src.intraday.types import SignalContext, SignalLevel

logger = logging.getLogger(__name__)

MORNING_OPEN = (9, 30)
MORNING_CLOSE = (11, 30)
AFTERNOON_OPEN = (13, 0)
AFTERNOON_CLOSE = (15, 0)


def is_trading_hours(dt: Optional[datetime] = None) -> bool:
    if dt is None:
        dt = datetime.now()
    if dt.weekday() >= 5:
        return False
    t = (dt.hour, dt.minute)
    in_morning = MORNING_OPEN <= t <= MORNING_CLOSE
    in_afternoon = AFTERNOON_OPEN <= t <= AFTERNOON_CLOSE
    return in_morning or in_afternoon


class IntradayScheduler:
    """Runs the intraday monitoring loop."""

    def __init__(
        self,
        fetcher: Optional[IntradayDataFetcher] = None,
        store: Optional[IntradaySignalStore] = None,
        notifier: Optional[IntradayNotifier] = None,
        watch_list: Optional[List[str]] = None,
        poll_interval_minutes: int = 15,
        simulation: bool = True,
    ) -> None:
        self._fetcher = fetcher or IntradayDataFetcher()
        self._store = store or IntradaySignalStore()
        self._notifier = notifier or IntradayNotifier(simulation=simulation)
        self._watch_list = watch_list or []
        self._poll_interval = poll_interval_minutes
        self._simulation = simulation
        self._engine = SignalEngine()
        for cls in ALL_SIGNALS:
            self._engine.register(cls())

    def run_single_poll(self) -> None:
        today = datetime.now().date()
        for ts_code in self._watch_list:
            try:
                self._poll_stock(ts_code, today)
            except Exception:
                logger.exception("Error polling %s", ts_code)

    def _poll_stock(self, ts_code: str, today) -> None:
        df = self._fetcher.fetch_minute_bars(stock_code=ts_code, freq="5min", bars=60)
        if df is None or df.empty:
            logger.debug("No data for %s", ts_code)
            return
        ctx = SignalContext(ts_code=ts_code)
        results = self._engine.detect(df, ctx)
        for result in results:
            if self._store.has_fired_today(ts_code, result.signal_name, today):
                logger.debug("Already fired: %s on %s", result.signal_name, ts_code)
                continue
            self._store.save(result)
            if result.level >= SignalLevel.STRONG:
                self._notifier.notify(result)

    def run_loop(self, max_iterations: int = 0) -> None:
        iteration = 0
        logger.info("Starting intraday monitor (simulation=%s)", self._simulation)
        while True:
            if max_iterations > 0 and iteration >= max_iterations:
                logger.info("Reached max iterations (%d), stopping", max_iterations)
                break
            if not is_trading_hours():
                now = datetime.now()
                if now.hour >= 15:
                    logger.info("Market closed, exiting monitor loop")
                    break
                logger.debug("Outside trading hours, sleeping...")
                time.sleep(60)
                continue
            logger.info("Poll iteration %d", iteration + 1)
            self.run_single_poll()
            iteration += 1
            sleep_seconds = self._poll_interval * 60
            logger.info("Sleeping %d seconds until next poll", sleep_seconds)
            time.sleep(sleep_seconds)
