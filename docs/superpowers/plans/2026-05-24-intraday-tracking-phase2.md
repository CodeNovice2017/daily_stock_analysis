# Intraday Monitoring Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the intraday monitoring loop with SQLite persistence, Telegram notifications, and a live simulation mode.

**Architecture:** Scheduler polls watch-list stocks every 15 minutes during A-share trading hours. Detected signals are persisted to SQLite and pushed via the existing NotificationService. Monitor and evolve modes are wired into `intraday_main.py`.

**Tech Stack:** Python 3.12, SQLAlchemy (reusing `DatabaseManager`), `schedule` library (existing), `src/core/trading_calendar.py` for market phase, `NotificationService` for push.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/intraday/store.py` | Create | SQLAlchemy model + CRUD for signal records |
| `src/intraday/scheduler.py` | Create | Trading-hours detection + 15-min polling loop |
| `src/intraday/notifier.py` | Create | Format signals as Telegram messages + dispatch |
| `intraday_main.py` | Modify | Wire `--intraday-monitor` and `--intraday-evolve` |
| `tests/test_intraday_store.py` | Create | Tests for store CRUD |
| `tests/test_intraday_scheduler.py` | Create | Tests for scheduler time logic |
| `tests/test_intraday_notifier.py` | Create | Tests for message formatting |

---

### Task 1: Signal Store (`store.py`)

**Files:**
- Create: `src/intraday/store.py`
- Create: `tests/test_intraday_store.py`

The store persists signal triggers to SQLite, reusing the project's existing `DatabaseManager` / SQLAlchemy setup. It creates its own table (`intraday_signals`) in the same database.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for intraday signal store (SQLite persistence)."""
import pytest
from datetime import datetime, date

from src.intraday.store import IntradaySignalStore
from src.intraday.types import SignalLevel, SignalResult


@pytest.fixture
def store(tmp_path):
    """Create a store with a temporary SQLite database."""
    db_path = str(tmp_path / "test_intraday.db")
    return IntradaySignalStore(db_url=f"sqlite:///{db_path}")


def _make_result(ts_code="002156.SZ", signal_name="volume_breakout", price=62.35):
    return SignalResult(
        signal_name=signal_name,
        level=SignalLevel.STRONG,
        triggered_at=datetime(2026, 5, 24, 10, 45),
        ts_code=ts_code,
        price=price,
        data={"volume_ratio": 3.8},
    )


class TestIntradaySignalStore:
    def test_save_and_query(self, store):
        result = _make_result()
        store.save(result)
        records = store.query_by_date(date(2026, 5, 24))
        assert len(records) == 1
        assert records[0]["ts_code"] == "002156.SZ"
        assert records[0]["signal_name"] == "volume_breakout"
        assert records[0]["price"] == 62.35

    def test_query_empty_date(self, store):
        records = store.query_by_date(date(2026, 1, 1))
        assert records == []

    def test_query_by_ts_code(self, store):
        store.save(_make_result("002156.SZ"))
        store.save(_make_result("600460.SH"))
        records = store.query_by_date(date(2026, 5, 24), ts_code="002156.SZ")
        assert len(records) == 1
        assert records[0]["ts_code"] == "002156.SZ"

    def test_save_multiple_and_query_all(self, store):
        store.save(_make_result(signal_name="volume_breakout"))
        store.save(_make_result(signal_name="panic_drop"))
        records = store.query_by_date(date(2026, 5, 24))
        assert len(records) == 2

    def test_has_fired_today(self, store):
        result = _make_result()
        assert not store.has_fired_today("002156.SZ", "volume_breakout", date(2026, 5, 24))
        store.save(result)
        assert store.has_fired_today("002156.SZ", "volume_breakout", date(2026, 5, 24))

    def test_daily_stats(self, store):
        store.save(_make_result(ts_code="002156.SZ", signal_name="volume_breakout", price=60.0))
        store.save(_make_result(ts_code="600460.SH", signal_name="panic_drop", price=28.0))
        stats = store.get_daily_stats(date(2026, 5, 24))
        assert stats["total_signals"] == 2
        assert "volume_breakout" in stats["by_signal"]
        assert "panic_drop" in stats["by_signal"]
        assert stats["by_ts_code"]["002156.SZ"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_intraday_store.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Write implementation**

```python
"""SQLite persistence for intraday signal records.

Uses SQLAlchemy directly (not the shared DatabaseManager) to keep
the intraday module's storage independent and easily testable with
temp databases.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from src.intraday.types import SignalLevel, SignalResult

logger = logging.getLogger(__name__)

Base = declarative_base()


class IntradaySignalRecord(Base):
    __tablename__ = "intraday_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    triggered_at = Column(DateTime, nullable=False)
    ts_code = Column(String(16), nullable=False, index=True)
    signal_name = Column(String(64), nullable=False)
    level = Column(String(16), nullable=False)
    price = Column(Float, nullable=False)
    data = Column(Text, nullable=True)


class IntradaySignalStore:
    """Persists and queries intraday signal records via SQLite."""

    def __init__(self, db_url: str = "") -> None:
        if not db_url:
            from src.config import get_config
            config = get_config()
            db_url = config.get_db_url()
        self._engine = create_engine(db_url, pool_pre_ping=True)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)

    def save(self, result: SignalResult) -> None:
        trade_date = result.triggered_at.date()
        record = IntradaySignalRecord(
            trade_date=trade_date,
            triggered_at=result.triggered_at,
            ts_code=result.ts_code,
            signal_name=result.signal_name,
            level=result.level.name,
            price=result.price,
            data=json.dumps(result.data) if result.data else None,
        )
        session = self._Session()
        try:
            session.add(record)
            session.commit()
            logger.info("Saved signal: %s on %s at %.2f", result.signal_name, result.ts_code, result.price)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def query_by_date(self, trade_date: date, ts_code: Optional[str] = None) -> List[Dict[str, Any]]:
        session = self._Session()
        try:
            q = session.query(IntradaySignalRecord).filter(IntradaySignalRecord.trade_date == trade_date)
            if ts_code:
                q = q.filter(IntradaySignalRecord.ts_code == ts_code)
            rows = q.order_by(IntradaySignalRecord.triggered_at).all()
            return [self._row_to_dict(r) for r in rows]
        finally:
            session.close()

    def has_fired_today(self, ts_code: str, signal_name: str, trade_date: date) -> bool:
        session = self._Session()
        try:
            return session.query(IntradaySignalRecord).filter(
                IntradaySignalRecord.ts_code == ts_code,
                IntradaySignalRecord.signal_name == signal_name,
                IntradaySignalRecord.trade_date == trade_date,
            ).first() is not None
        finally:
            session.close()

    def get_daily_stats(self, trade_date: date) -> Dict[str, Any]:
        records = self.query_by_date(trade_date)
        by_signal: Dict[str, int] = {}
        by_ts_code: Dict[str, int] = {}
        for r in records:
            by_signal[r["signal_name"]] = by_signal.get(r["signal_name"], 0) + 1
            by_ts_code[r["ts_code"]] = by_ts_code.get(r["ts_code"], 0) + 1
        return {
            "trade_date": str(trade_date),
            "total_signals": len(records),
            "by_signal": by_signal,
            "by_ts_code": by_ts_code,
        }

    @staticmethod
    def _row_to_dict(row: IntradaySignalRecord) -> Dict[str, Any]:
        return {
            "id": row.id,
            "trade_date": str(row.trade_date),
            "triggered_at": str(row.triggered_at),
            "ts_code": row.ts_code,
            "signal_name": row.signal_name,
            "level": row.level,
            "price": row.price,
            "data": json.loads(row.data) if row.data else {},
        }
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_intraday_store.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/intraday/store.py tests/test_intraday_store.py
git commit -m "feat(intraday): add SQLite signal store with query and dedup support"
```

---

### Task 2: Notifier (`notifier.py`)

**Files:**
- Create: `src/intraday/notifier.py`
- Create: `tests/test_intraday_notifier.py`

Formats `SignalResult` into Telegram-friendly messages and sends via `NotificationService`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for intraday notification formatting and dispatch."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.intraday.notifier import IntradayNotifier, format_signal_message
from src.intraday.types import SignalLevel, SignalResult


def _make_result(level=SignalLevel.STRONG, **overrides):
    defaults = dict(
        signal_name="volume_breakout",
        level=level,
        triggered_at=datetime(2026, 5, 24, 10, 45),
        ts_code="002156.SZ",
        price=62.35,
        data={"volume_ratio": 3.8, "breakout_price": 61.80},
    )
    defaults.update(overrides)
    return SignalResult(**defaults)


class TestFormatMessage:
    def test_strong_signal_format(self):
        result = _make_result()
        msg = format_signal_message(result, stock_name="通富微电")
        assert "放量突破" in msg or "volume_breakout" in msg
        assert "002156.SZ" in msg
        assert "62.35" in msg
        assert "10:45" in msg
        assert "STRONG" in msg

    def test_medium_signal_format(self):
        result = _make_result(level=SignalLevel.MEDIUM, signal_name="low_volume")
        msg = format_signal_message(result)
        assert "MEDIUM" in msg

    def test_simulation_label(self):
        result = _make_result()
        msg = format_signal_message(result, simulation=True)
        assert "模拟盘" in msg


class TestIntradayNotifier:
    def test_notify_strong_sends_message(self):
        mock_ns = MagicMock()
        mock_ns.send_with_results.return_value = MagicMock(success=True)
        notifier = IntradayNotifier(notification_service=mock_ns)
        result = _make_result()
        notifier.notify(result, stock_name="通富微电")
        mock_ns.send_with_results.assert_called_once()
        call_args = mock_ns.send_with_results.call_args
        assert call_args[1].get("route_type") == "alert" or (len(call_args[0]) > 0)

    def test_notify_medium_does_not_send(self):
        mock_ns = MagicMock()
        notifier = IntradayNotifier(notification_service=mock_ns)
        result = _make_result(level=SignalLevel.MEDIUM)
        notifier.notify(result)
        mock_ns.send_with_results.assert_not_called()

    def test_send_daily_summary(self):
        mock_ns = MagicMock()
        notifier = IntradayNotifier(notification_service=mock_ns)
        stats = {
            "trade_date": "2026-05-24",
            "total_signals": 5,
            "by_signal": {"volume_breakout": 3, "panic_drop": 2},
            "by_ts_code": {"002156.SZ": 3, "600460.SH": 2},
        }
        notifier.send_daily_summary(stats)
        mock_ns.send_with_results.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_intraday_notifier.py -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
"""Formats and dispatches intraday signal notifications.

Reuses the existing NotificationService for actual delivery.
Only STRONG signals trigger immediate push; MEDIUM signals go into
the daily summary only.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.intraday.types import SignalLevel, SignalResult

logger = logging.getLogger(__name__)

LEVEL_EMOJI = {
    SignalLevel.STRONG: "🔴",
    SignalLevel.MEDIUM: "🟡",
    SignalLevel.WEAK: "🟢",
}


def format_signal_message(
    result: SignalResult,
    stock_name: str = "",
    simulation: bool = False,
) -> str:
    emoji = LEVEL_EMOJI.get(result.level, "⚪")
    time_str = result.triggered_at.strftime("%H:%M")
    lines = [
        f"{emoji} {result.level.name} - {stock_name or result.ts_code} ({result.ts_code})",
        "─" * 24,
        f"信号：{result.signal_name}",
        f"时间：{time_str}",
        f"价格：{result.price:.2f}",
    ]
    for key, val in result.data.items():
        if isinstance(val, float):
            lines.append(f"{key}: {val:.2f}")
        else:
            lines.append(f"{key}: {val}")
    if simulation:
        lines.append("─" * 24)
        lines.append("⚡ 模拟盘模式 — 仅供参考，不构成投资建议")
    return "\n".join(lines)


def format_daily_summary(stats: Dict[str, Any]) -> str:
    trade_date = stats.get("trade_date", "unknown")
    total = stats.get("total_signals", 0)
    lines = [
        f"📊 盘中信号日报 — {trade_date}",
        "─" * 24,
        f"总信号数：{total}",
    ]
    by_signal = stats.get("by_signal", {})
    if by_signal:
        lines.append("")
        lines.append("按信号类型：")
        for name, count in sorted(by_signal.items(), key=lambda x: -x[1]):
            lines.append(f"  {name}: {count}")
    by_code = stats.get("by_ts_code", {})
    if by_code:
        lines.append("")
        lines.append("按股票：")
        for code, count in sorted(by_code.items(), key=lambda x: -x[1]):
            lines.append(f"  {code}: {count}")
    return "\n".join(lines)


class IntradayNotifier:
    """Dispatches intraday signal notifications via NotificationService."""

    def __init__(self, notification_service=None, simulation: bool = True) -> None:
        self._ns = notification_service
        self._simulation = simulation

    def _get_ns(self):
        if self._ns is not None:
            return self._ns
        from src.notification import get_notification_service
        return get_notification_service()

    def notify(self, result: SignalResult, stock_name: str = "") -> None:
        if result.level < SignalLevel.STRONG:
            logger.debug("Skipping notification for %s signal: %s", result.level.name, result.signal_name)
            return
        msg = format_signal_message(result, stock_name=stock_name, simulation=self._simulation)
        try:
            ns = self._get_ns()
            ns.send_with_results(msg, route_type="alert")
            logger.info("Sent notification for %s on %s", result.signal_name, result.ts_code)
        except Exception:
            logger.exception("Failed to send notification for %s", result.signal_name)

    def send_daily_summary(self, stats: Dict[str, Any]) -> None:
        msg = format_daily_summary(stats)
        try:
            ns = self._get_ns()
            ns.send_with_results(msg, route_type="report")
            logger.info("Sent daily summary for %s", stats.get("trade_date"))
        except Exception:
            logger.exception("Failed to send daily summary")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_intraday_notifier.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/intraday/notifier.py tests/test_intraday_notifier.py
git commit -m "feat(intraday): add notifier with Telegram formatting and daily summary"
```

---

### Task 3: Scheduler (`scheduler.py`)

**Files:**
- Create: `src/intraday/scheduler.py`
- Create: `tests/test_intraday_scheduler.py`

Manages the monitoring loop: detects trading hours, runs 15-min polls, coordinates data fetching → signal detection → persistence → notification.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for intraday scheduler — trading hours and polling logic."""
import pytest
from datetime import datetime, time
from unittest.mock import MagicMock, patch

from src.intraday.scheduler import IntradayScheduler, is_trading_hours


class TestTradingHours:
    def test_morning_trading(self):
        dt = datetime(2026, 5, 22, 10, 30)  # Friday
        assert is_trading_hours(dt) is True

    def test_afternoon_trading(self):
        dt = datetime(2026, 5, 22, 14, 0)
        assert is_trading_hours(dt) is True

    def test_lunch_break(self):
        dt = datetime(2026, 5, 22, 12, 0)
        assert is_trading_hours(dt) is False

    def test_weekend(self):
        dt = datetime(2026, 5, 23, 10, 30)  # Saturday
        assert is_trading_hours(dt) is False

    def test_before_open(self):
        dt = datetime(2026, 5, 22, 9, 15)
        assert is_trading_hours(dt) is False

    def test_after_close(self):
        dt = datetime(2026, 5, 22, 15, 5)
        assert is_trading_hours(dt) is False

    def test_boundary_open(self):
        dt = datetime(2026, 5, 22, 9, 30)
        assert is_trading_hours(dt) is True

    def test_boundary_close(self):
        dt = datetime(2026, 5, 22, 15, 0)
        assert is_trading_hours(dt) is True


class TestIntradayScheduler:
    def test_run_single_poll(self):
        """Single poll cycle: fetch data → detect → save → notify."""
        mock_fetcher = MagicMock()
        mock_store = MagicMock()
        mock_notifier = MagicMock()

        import pandas as pd
        import numpy as np
        rows = 48
        dates = pd.date_range("2026-05-22 09:30", periods=rows, freq="5min")
        np.random.seed(42)
        df = pd.DataFrame({
            "trade_time": dates,
            "open": np.full(rows, 60.0),
            "high": np.full(rows, 60.2),
            "low": np.full(rows, 59.8),
            "close": np.full(rows, 60.1),
            "vol": np.full(rows, 100000.0),
        })
        mock_fetcher.fetch_minute_bars.return_value = df
        mock_store.has_fired_today.return_value = False

        scheduler = IntradayScheduler(
            fetcher=mock_fetcher,
            store=mock_store,
            notifier=mock_notifier,
            watch_list=["002156.SZ"],
        )
        scheduler.run_single_poll()

        mock_fetcher.fetch_minute_bars.assert_called_once_with(
            ts_code="002156.SZ", freq="5min", bars=60,
        )
        mock_store.save.assert_not_called()  # no signals fired on flat data

    def test_run_single_poll_with_signal(self):
        """Signal fires → store.save and notifier.notify are called."""
        mock_fetcher = MagicMock()
        mock_store = MagicMock()
        mock_notifier = MagicMock()

        import pandas as pd
        import numpy as np
        rows = 25
        dates = pd.date_range("2026-05-22 09:30", periods=rows, freq="5min")
        close = np.full(rows, 60.0)
        close[24] = 63.0  # breakout
        vol = np.full(rows, 100000.0)
        vol[24] = 500000.0
        df = pd.DataFrame({
            "trade_time": dates,
            "open": close - 0.1,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "vol": vol,
        })
        mock_fetcher.fetch_minute_bars.return_value = df
        mock_store.has_fired_today.return_value = False

        scheduler = IntradayScheduler(
            fetcher=mock_fetcher,
            store=mock_store,
            notifier=mock_notifier,
            watch_list=["002156.SZ"],
        )
        scheduler.run_single_poll()

        assert mock_store.save.call_count >= 1
        assert mock_notifier.notify.call_count >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_intraday_scheduler.py -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
"""Intraday monitoring scheduler — trading-hours detection and polling loop.

Coordinates: data fetch → signal detection → persistence → notification.
Uses `schedule` library for the main loop, consistent with main.py.
"""
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
    """Check if a datetime falls within A-share trading hours (simple weekday check).

    Does NOT check holidays — use trading_calendar for that in production.
    """
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
        """Execute one polling cycle across all watch-list stocks."""
        today = datetime.now().date()
        for ts_code in self._watch_list:
            try:
                self._poll_stock(ts_code, today)
            except Exception:
                logger.exception("Error polling %s", ts_code)

    def _poll_stock(self, ts_code: str, today) -> None:
        df = self._fetcher.fetch_minute_bars(ts_code=ts_code, freq="5min", bars=60)
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
        """Main monitoring loop. Blocks until market closes or max_iterations reached."""
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
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_intraday_scheduler.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/intraday/scheduler.py tests/test_intraday_scheduler.py
git commit -m "feat(intraday): add scheduler with trading-hours detection and polling loop"
```

---

### Task 4: Wire CLI — `--intraday-monitor` and `--intraday-evolve`

**Files:**
- Modify: `intraday_main.py`

Adds actual functionality to `--intraday-monitor` (starts scheduler loop) and `--intraday-evolve` (prints daily stats from store).

- [ ] **Step 1: Read current intraday_main.py**

Read: `intraday_main.py`

- [ ] **Step 2: Update monitor and evolve modes**

Replace the stub `logger.info("Monitor mode not yet implemented (Phase 2)")` with actual scheduler invocation:

```python
elif args.intraday_monitor:
    run_monitor(args)
```

Replace the stub evolve with:

```python
elif args.intraday_evolve:
    run_evolve(args)
```

Add these two new functions:

```python
def run_monitor(args) -> None:
    from src.config import get_config
    from src.intraday.scheduler import IntradayScheduler

    config = get_config()
    watch_list = config.intraday_watch_list
    if not watch_list:
        logger.error("INTRADAY_WATCH_LIST is empty. Set it in .env")
        sys.exit(1)

    scheduler = IntradayScheduler(
        watch_list=watch_list,
        poll_interval_minutes=config.intraday_poll_interval,
        simulation=True,
    )
    logger.info("Starting intraday monitor for %d stocks: %s", len(watch_list), ", ".join(watch_list))
    try:
        scheduler.run_loop()
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")


def run_evolve(args) -> None:
    from datetime import date
    from src.config import get_config
    from src.intraday.store import IntradaySignalStore
    from src.intraday.notifier import IntradayNotifier

    config = get_config()
    store = IntradaySignalStore()
    today = date.today()
    stats = store.get_daily_stats(today)

    if stats["total_signals"] == 0:
        print(f"No signals recorded for {today}")
        return

    print(f"\n===== Daily Review — {today} =====")
    print(f"Total signals: {stats['total_signals']}")
    for name, count in stats.get("by_signal", {}).items():
        print(f"  {name}: {count}")
    for code, count in stats.get("by_ts_code", {}).items():
        print(f"  {code}: {count}")

    notifier = IntradayNotifier(simulation=True)
    notifier.send_daily_summary(stats)
    print("\nDaily summary sent.")
```

- [ ] **Step 3: Verify compilation and help**

Run: `.venv/bin/python -c "import intraday_main; print('OK')"`
Run: `.venv/bin/python intraday_main.py --help`
Expected: Both succeed.

- [ ] **Step 4: Commit**

```bash
git add intraday_main.py
git commit -m "feat(intraday): wire --intraday-monitor and --intraday-evolve CLI modes"
```

---

### Task 5: Final Validation

- [ ] **Step 1: Run all intraday tests together**

Run: `.venv/bin/python -m pytest tests/test_intraday_*.py -v`
Expected: All tests PASS (previous 34 + new ~22 = ~56 total)

- [ ] **Step 2: Compile-check all new files**

Run:
```bash
.venv/bin/python -m py_compile src/intraday/store.py && \
.venv/bin/python -m py_compile src/intraday/notifier.py && \
.venv/bin/python -m py_compile src/intraday/scheduler.py && \
echo "All compile OK"
```
Expected: "All compile OK"

- [ ] **Step 3: Verify CLI modes**

Run: `.venv/bin/python intraday_main.py --help`
Expected: Shows all modes including `--intraday-monitor` and `--intraday-evolve`
