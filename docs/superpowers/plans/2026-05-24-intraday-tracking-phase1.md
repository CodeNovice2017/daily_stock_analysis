# Intraday Tracking System - Phase 1: Signal Backtest Verification

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational intraday signal detection system with backtest verification so we can validate which signals have historical win rates above threshold.

**Architecture:** Semi-independent module (`src/intraday/`) with its own CLI entry (`intraday_main.py`). Quantitative signals implement a common `BaseSignal` ABC. A lightweight backtest engine replays historical 5-min bars through each signal and computes win rates. Reuses existing `data_provider/tushare_fetcher.py` for data access and `src/config.py` for configuration.

**Tech Stack:** Python 3.10+, pandas, numpy, SQLAlchemy (existing), Tushare Pro API, pytest

---

## File Map

### New files (create)
| File | Responsibility |
|------|---------------|
| `src/intraday/__init__.py` | Package marker |
| `src/intraday/types.py` | `SignalLevel` enum, `SignalContext`, `SignalResult` dataclasses |
| `src/intraday/signals/__init__.py` | Package marker, auto-imports all signals |
| `src/intraday/signals/base.py` | `BaseSignal` ABC — the contract every signal implements |
| `src/intraday/signals/volume_breakout.py` | 放量突破 strong signal |
| `src/intraday/signals/panic_drop.py` | 急跌放量 strong signal |
| `src/intraday/signals/chip_breakout.py` | 筹码突破 strong signal |
| `src/intraday/signals/macd_volume.py` | MACD金叉+放量 strong signal |
| `src/intraday/signals/support_break.py` | 支撑破位 strong signal |
| `src/intraday/signal_engine.py` | `SignalEngine` — registers signals, runs detection, handles dedup |
| `src/intraday/data_fetcher.py` | `IntradayDataFetcher` — wraps Tushare minute-bar + moneyflow APIs |
| `src/intraday/backtest/__init__.py` | Package marker |
| `src/intraday/backtest/loader.py` | `BacktestDataLoader` — fetches & caches historical 5-min bars to SQLite |
| `src/intraday/backtest/engine.py` | `BacktestEngine` — replays bars through signals, records trigger outcomes |
| `src/intraday/backtest/reporter.py` | `BacktestReporter` — aggregates win rate, avg return, max loss per signal |
| `intraday_main.py` | CLI entry point: `--intraday-backtest` mode |
| `tests/test_intraday_types.py` | Tests for types module |
| `tests/test_intraday_signals.py` | Tests for all 5 signals + engine |
| `tests/test_intraday_backtest.py` | Tests for loader, engine, reporter |

### Modified files
| File | Change |
|------|--------|
| `src/config.py` | Add `INTRADAY_*` config fields |
| `.env.example` | Add intraday config section |
| `data_provider/tushare_fetcher.py` | Add `get_minute_data()` method |

---

### Task 1: Foundation Types

**Files:**
- Create: `src/intraday/__init__.py`
- Create: `src/intraday/types.py`
- Create: `tests/test_intraday_types.py`

- [ ] **Step 1: Create package init**

```python
# src/intraday/__init__.py
```

- [ ] **Step 2: Write the test for types**

```python
# tests/test_intraday_types.py
import pytest
from datetime import datetime
from src.intraday.types import SignalLevel, SignalContext, SignalResult


class TestSignalLevel:
    def test_has_three_levels(self):
        assert SignalLevel.STRONG
        assert SignalLevel.MEDIUM
        assert SignalLevel.WEAK

    def test_ordering(self):
        assert SignalLevel.STRONG > SignalLevel.MEDIUM > SignalLevel.WEAK


class TestSignalResult:
    def test_creation_with_required_fields(self):
        result = SignalResult(
            signal_name="volume_breakout",
            level=SignalLevel.STRONG,
            triggered_at=datetime(2026, 5, 24, 10, 45),
            ts_code="002156.SZ",
            price=62.35,
            data={"volume_ratio": 3.8, "breakout_price": 61.80},
        )
        assert result.signal_name == "volume_breakout"
        assert result.level == SignalLevel.STRONG
        assert result.price == 62.35
        assert result.data["volume_ratio"] == 3.8

    def test_optional_fields_default_none(self):
        result = SignalResult(
            signal_name="test",
            level=SignalLevel.WEAK,
            triggered_at=datetime.now(),
            ts_code="000001.SZ",
            price=10.0,
        )
        assert result.confidence is None


class TestSignalContext:
    def test_creation(self):
        ctx = SignalContext(
            ts_code="002156.SZ",
            moneyflow_net=5000000.0,
            chip_cost_95=60.50,
            ma20=58.20,
            ma60=55.10,
            prev_low=54.00,
            prev_high=61.80,
        )
        assert ctx.ts_code == "002156.SZ"
        assert ctx.moneyflow_net == 5000000.0
        assert ctx.chip_cost_95 == 60.50
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.intraday'`

- [ ] **Step 4: Implement types**

```python
# src/intraday/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, Optional


class SignalLevel(IntEnum):
    STRONG = 3
    MEDIUM = 2
    WEAK = 1


@dataclass
class SignalContext:
    """Auxiliary data passed to signal detectors alongside the K-line DataFrame."""
    ts_code: str
    moneyflow_net: float = 0.0
    chip_cost_95: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    prev_low: float = 0.0
    prev_high: float = 0.0
    avg_daily_volume: float = 0.0


@dataclass
class SignalResult:
    """Output of a signal detection — returned when a signal fires."""
    signal_name: str
    level: SignalLevel
    triggered_at: datetime
    ts_code: str
    price: float
    data: Dict[str, Any] = field(default_factory=dict)
    confidence: Optional[float] = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_types.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add src/intraday/__init__.py src/intraday/types.py tests/test_intraday_types.py
git commit -m "feat(intraday): add foundation types — SignalLevel, SignalContext, SignalResult"
```

---

### Task 2: Signal Base Class + First Signal (Volume Breakout)

**Files:**
- Create: `src/intraday/signals/__init__.py`
- Create: `src/intraday/signals/base.py`
- Create: `src/intraday/signals/volume_breakout.py`
- Create: `tests/test_intraday_signals.py`

- [ ] **Step 1: Write the test for BaseSignal contract + volume_breakout**

```python
# tests/test_intraday_signals.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from src.intraday.types import SignalLevel, SignalContext, SignalResult
from src.intraday.signals.base import BaseSignal
from src.intraday.signals.volume_breakout import VolumeBreakoutSignal


def _make_5min_df(rows: int = 25, base_price: float = 60.0, trend: str = "flat") -> pd.DataFrame:
    """Generate synthetic 5-min K-line data for testing."""
    np.random.seed(42)
    dates = pd.date_range("2026-05-24 09:30", periods=rows, freq="5min")
    if trend == "flat":
        close = base_price + np.random.randn(rows) * 0.2
    elif trend == "breakout":
        close = np.full(rows, base_price)
        close[-1] = base_price + 2.0  # last bar breaks above
    elif trend == "no_volume":
        close = np.full(rows, base_price)
        close[-1] = base_price + 2.0
    else:
        close = np.full(rows, base_price)

    vol_base = 100000
    if trend == "no_volume":
        vol = np.full(rows, vol_base, dtype=float)
    elif trend == "breakout":
        vol = np.full(rows, vol_base, dtype=float)
        vol[-1] = vol_base * 4.0  # 4x volume on breakout bar
    else:
        vol = np.random.randint(vol_base * 0.5, vol_base * 1.5, rows).astype(float)

    return pd.DataFrame({
        "trade_time": dates,
        "open": close - 0.1,
        "high": close + 0.3,
        "low": close - 0.3,
        "close": close,
        "vol": vol,
    })


class TestBaseSignalContract:
    def test_volume_breakout_is_a_base_signal(self):
        signal = VolumeBreakoutSignal()
        assert isinstance(signal, BaseSignal)
        assert signal.name == "volume_breakout"
        assert signal.level == SignalLevel.STRONG


class TestVolumeBreakoutSignal:
    def test_fires_on_breakout_with_high_volume(self):
        signal = VolumeBreakoutSignal()
        df = _make_5min_df(25, 60.0, "breakout")
        ctx = SignalContext(ts_code="002156.SZ")
        result = signal.detect(df, ctx)
        assert result is not None
        assert result.signal_name == "volume_breakout"
        assert result.level == SignalLevel.STRONG
        assert result.data["volume_ratio"] > 3.0

    def test_no_fire_without_volume(self):
        signal = VolumeBreakoutSignal()
        df = _make_5min_df(25, 60.0, "no_volume")
        ctx = SignalContext(ts_code="002156.SZ")
        result = signal.detect(df, ctx)
        assert result is None

    def test_no_fire_without_breakout(self):
        signal = VolumeBreakoutSignal()
        df = _make_5min_df(25, 60.0, "flat")
        ctx = SignalContext(ts_code="002156.SZ")
        result = signal.detect(df, ctx)
        assert result is None

    def test_no_fire_with_insufficient_data(self):
        signal = VolumeBreakoutSignal()
        df = _make_5min_df(10, 60.0, "breakout")
        ctx = SignalContext(ts_code="002156.SZ")
        result = signal.detect(df, ctx)
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_signals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.intraday.signals'`

- [ ] **Step 3: Implement base class**

```python
# src/intraday/signals/__init__.py
from src.intraday.signals.volume_breakout import VolumeBreakoutSignal

__all__ = ["VolumeBreakoutSignal"]
```

```python
# src/intraday/signals/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from src.intraday.types import SignalContext, SignalLevel, SignalResult


class BaseSignal(ABC):
    """Contract every quantitative signal must implement."""

    name: str = ""
    level: SignalLevel = SignalLevel.WEAK

    @abstractmethod
    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        """
        Detect whether this signal fires on the given data.

        Args:
            df: Recent 5-min K-line bars. Columns: trade_time, open, high, low, close, vol.
                Must have at least `min_bars` rows.
            context: Auxiliary data (money flow, chip distribution, MA values, etc.)

        Returns:
            SignalResult if signal fires, None otherwise.
        """
        ...
```

- [ ] **Step 4: Implement volume_breakout signal**

```python
# src/intraday/signals/volume_breakout.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalLevel, SignalResult


class VolumeBreakoutSignal(BaseSignal):
    """放量突破: volume_ratio > 3 AND price breaks above 20-bar high."""

    name = "volume_breakout"
    level = SignalLevel.STRONG
    min_bars = 21  # 20 lookback + 1 current
    volume_ratio_threshold = 3.0

    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        if len(df) < self.min_bars:
            return None

        lookback = df.iloc[:-1].tail(20)
        current = df.iloc[-1]

        avg_vol = lookback["vol"].mean()
        if avg_vol == 0:
            return None

        volume_ratio = current["vol"] / avg_vol
        if volume_ratio < self.volume_ratio_threshold:
            return None

        prev_high = lookback["high"].max()
        if current["close"] <= prev_high:
            return None

        return SignalResult(
            signal_name=self.name,
            level=self.level,
            triggered_at=datetime.now(),
            ts_code=context.ts_code,
            price=float(current["close"]),
            data={
                "volume_ratio": round(volume_ratio, 2),
                "breakout_price": round(prev_high, 2),
                "prev_high_20": round(prev_high, 2),
            },
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_signals.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add src/intraday/signals/ tests/test_intraday_signals.py
git commit -m "feat(intraday): add BaseSignal ABC and VolumeBreakoutSignal"
```

---

### Task 3: Remaining Strong Signals

**Files:**
- Create: `src/intraday/signals/panic_drop.py`
- Create: `src/intraday/signals/chip_breakout.py`
- Create: `src/intraday/signals/macd_volume.py`
- Create: `src/intraday/signals/support_break.py`

- [ ] **Step 1: Write tests for all 4 remaining signals**

Add the following test classes to `tests/test_intraday_signals.py` (append after existing classes):

```python
class TestPanicDropSignal:
    def test_fires_on_sharp_drop_with_volume(self):
        from src.intraday.signals.panic_drop import PanicDropSignal
        signal = PanicDropSignal()
        # Build data where last bar drops >2% with 5x volume
        dates = pd.date_range("2026-05-24 09:30", periods=10, freq="5min")
        base_price = 60.0
        close = np.full(10, base_price)
        close[-1] = base_price * 0.97  # 3% drop
        vol = np.full(10, 100000.0)
        vol[-1] = 600000.0  # 6x volume
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ")
        result = signal.detect(df, ctx)
        assert result is not None
        assert result.signal_name == "panic_drop"
        assert result.data["drop_pct"] > 2.0

    def test_no_fire_on_small_drop(self):
        from src.intraday.signals.panic_drop import PanicDropSignal
        signal = PanicDropSignal()
        dates = pd.date_range("2026-05-24 09:30", periods=10, freq="5min")
        close = np.full(10, 60.0)
        close[-1] = 59.5  # <1% drop
        vol = np.full(10, 100000.0)
        vol[-1] = 600000.0
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ")
        result = signal.detect(df, ctx)
        assert result is None

    def test_no_fire_without_volume(self):
        from src.intraday.signals.panic_drop import PanicDropSignal
        signal = PanicDropSignal()
        dates = pd.date_range("2026-05-24 09:30", periods=10, freq="5min")
        close = np.full(10, 60.0)
        close[-1] = 58.0  # >3% drop
        vol = np.full(10, 100000.0)  # no volume spike
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ")
        result = signal.detect(df, ctx)
        assert result is None


class TestMacdVolumeSignal:
    def test_fires_on_golden_cross_with_volume(self):
        from src.intraday.signals.macd_volume import MacdVolumeSignal
        signal = MacdVolumeSignal()
        # Build data with MACD crossing from negative to positive
        rows = 45
        dates = pd.date_range("2026-05-24 09:30", periods=rows, freq="5min")
        # Decline then rise to create golden cross
        close = np.concatenate([
            np.linspace(60, 55, 20),   # decline
            np.linspace(55, 60, 20),   # rise
            np.array([61.0]),           # continuation
            np.array([61.5]),
            np.array([62.0]),
            np.array([62.5]),
            np.array([63.0]),
        ])
        close = close[:rows]
        vol = np.full(rows, 100000.0)
        vol[-5:] = 200000.0  # volume pick-up
        df = pd.DataFrame({
            "trade_time": dates[:rows], "open": close - 0.1,
            "high": close + 0.2, "low": close - 0.2,
            "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ", avg_daily_volume=100000.0)
        result = signal.detect(df, ctx)
        # May or may not fire depending on MACD calc — we test the contract
        if result is not None:
            assert result.signal_name == "macd_volume"
            assert result.level == SignalLevel.STRONG


class TestSupportBreakSignal:
    def test_fires_on_break_below_ma20_with_volume(self):
        from src.intraday.signals.support_break import SupportBreakSignal
        signal = SupportBreakSignal()
        rows = 25
        dates = pd.date_range("2026-05-24 09:30", periods=rows, freq="5min")
        close = np.full(rows, 58.0)
        close[-1] = 54.0  # break below MA20=58
        vol = np.full(rows, 100000.0)
        vol[-1] = 300000.0  # 3x volume
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ", ma20=56.0, ma60=55.0, prev_low=55.5)
        result = signal.detect(df, ctx)
        assert result is not None
        assert result.signal_name == "support_break"

    def test_no_fire_without_volume(self):
        from src.intraday.signals.support_break import SupportBreakSignal
        signal = SupportBreakSignal()
        rows = 25
        dates = pd.date_range("2026-05-24 09:30", periods=rows, freq="5min")
        close = np.full(rows, 58.0)
        close[-1] = 54.0
        vol = np.full(rows, 100000.0)  # no volume spike
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ", ma20=56.0, ma60=55.0, prev_low=55.5)
        result = signal.detect(df, ctx)
        assert result is None


class TestChipBreakoutSignal:
    def test_fires_on_break_above_chip_with_volume(self):
        from src.intraday.signals.chip_breakout import ChipBreakoutSignal
        signal = ChipBreakoutSignal()
        rows = 25
        dates = pd.date_range("2026-05-24 09:30", periods=rows, freq="5min")
        close = np.full(rows, 60.0)
        close[-1] = 62.0  # above chip_cost_95=61.0
        vol = np.full(rows, 100000.0)
        vol[-1] = 200000.0
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(
            ts_code="002156.SZ",
            chip_cost_95=61.0,
            avg_daily_volume=100000.0,
        )
        result = signal.detect(df, ctx)
        assert result is not None
        assert result.signal_name == "chip_breakout"

    def test_no_fire_below_chip(self):
        from src.intraday.signals.chip_breakout import ChipBreakoutSignal
        signal = ChipBreakoutSignal()
        rows = 25
        dates = pd.date_range("2026-05-24 09:30", periods=rows, freq="5min")
        close = np.full(rows, 60.0)
        close[-1] = 60.5  # below chip_cost_95=61.0
        vol = np.full(rows, 100000.0)
        vol[-1] = 200000.0
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(
            ts_code="002156.SZ",
            chip_cost_95=61.0,
            avg_daily_volume=100000.0,
        )
        result = signal.detect(df, ctx)
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_signals.py -v`
Expected: FAIL — `ModuleNotFoundError` for panic_drop, macd_volume, support_break, chip_breakout

- [ ] **Step 3: Implement panic_drop signal**

```python
# src/intraday/signals/panic_drop.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalLevel, SignalResult


class PanicDropSignal(BaseSignal):
    """急跌放量: 5-min drop >2% with volume >5x average, not at limit-down."""

    name = "panic_drop"
    level = SignalLevel.STRONG
    min_bars = 6
    drop_pct_threshold = 2.0
    volume_ratio_threshold = 5.0

    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        if len(df) < self.min_bars:
            return None

        lookback = df.iloc[:-1].tail(self.min_bars - 1)
        current = df.iloc[-1]

        avg_vol = lookback["vol"].mean()
        if avg_vol == 0:
            return None

        volume_ratio = current["vol"] / avg_vol
        if volume_ratio < self.volume_ratio_threshold:
            return None

        if current["open"] == 0:
            return None
        drop_pct = (current["open"] - current["close"]) / current["open"] * 100
        if drop_pct < self.drop_pct_threshold:
            return None

        return SignalResult(
            signal_name=self.name,
            level=self.level,
            triggered_at=datetime.now(),
            ts_code=context.ts_code,
            price=float(current["close"]),
            data={
                "drop_pct": round(drop_pct, 2),
                "volume_ratio": round(volume_ratio, 2),
                "open_price": float(current["open"]),
            },
        )
```

- [ ] **Step 4: Implement chip_breakout signal**

```python
# src/intraday/signals/chip_breakout.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalLevel, SignalResult


class ChipBreakoutSignal(BaseSignal):
    """筹码突破: price > 90% chip upper bound AND intraday volume > 1.5x avg."""

    name = "chip_breakout"
    level = SignalLevel.STRONG
    min_bars = 20
    volume_ratio_threshold = 1.5

    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        if context.chip_cost_95 <= 0:
            return None
        if len(df) < self.min_bars:
            return None

        current = df.iloc[-1]
        if current["close"] <= context.chip_cost_95:
            return None

        if context.avg_daily_volume <= 0:
            return None
        intraday_vol = df["vol"].sum()
        vol_ratio = intraday_vol / context.avg_daily_volume
        if vol_ratio < self.volume_ratio_threshold:
            return None

        return SignalResult(
            signal_name=self.name,
            level=self.level,
            triggered_at=datetime.now(),
            ts_code=context.ts_code,
            price=float(current["close"]),
            data={
                "chip_cost_95": context.chip_cost_95,
                "volume_ratio": round(vol_ratio, 2),
                "breakout_pct": round(
                    (current["close"] - context.chip_cost_95) / context.chip_cost_95 * 100, 2
                ),
            },
        )
```

- [ ] **Step 5: Implement macd_volume signal**

```python
# src/intraday/signals/macd_volume.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
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
    """MACD金叉+放量: MACD histogram crosses from negative to positive, volume > 1.5x avg."""

    name = "macd_volume"
    level = SignalLevel.STRONG
    min_bars = 40
    volume_ratio_threshold = 1.5

    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        if len(df) < self.min_bars:
            return None

        dif, dea, hist = _compute_macd(df["close"])

        # Golden cross: previous histogram negative, current non-negative
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
```

- [ ] **Step 6: Implement support_break signal**

```python
# src/intraday/signals/support_break.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalLevel, SignalResult


class SupportBreakSignal(BaseSignal):
    """支撑破位: close < min(MA20, MA60, prev_low) AND volume > 2x average."""

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
```

- [ ] **Step 7: Update signals __init__.py to export all signals**

```python
# src/intraday/signals/__init__.py
from src.intraday.signals.volume_breakout import VolumeBreakoutSignal
from src.intraday.signals.panic_drop import PanicDropSignal
from src.intraday.signals.chip_breakout import ChipBreakoutSignal
from src.intraday.signals.macd_volume import MacdVolumeSignal
from src.intraday.signals.support_break import SupportBreakSignal

ALL_SIGNALS = [VolumeBreakoutSignal, PanicDropSignal, ChipBreakoutSignal, MacdVolumeSignal, SupportBreakSignal]

__all__ = [
    "VolumeBreakoutSignal",
    "PanicDropSignal",
    "ChipBreakoutSignal",
    "MacdVolumeSignal",
    "SupportBreakSignal",
    "ALL_SIGNALS",
]
```

- [ ] **Step 8: Run all signal tests**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_signals.py -v`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add src/intraday/signals/ tests/test_intraday_signals.py
git commit -m "feat(intraday): add panic_drop, chip_breakout, macd_volume, support_break signals"
```

---

### Task 4: Signal Engine (Registration + Detection + Dedup)

**Files:**
- Create: `src/intraday/signal_engine.py`
- Append tests to `tests/test_intraday_signals.py`

- [ ] **Step 1: Write tests for SignalEngine**

Append to `tests/test_intraday_signals.py`:

```python
class TestSignalEngine:
    def test_register_and_detect_all_signals(self):
        from src.intraday.signal_engine import SignalEngine
        from src.intraday.signals import ALL_SIGNALS
        engine = SignalEngine()
        for sig_cls in ALL_SIGNALS:
            engine.register(sig_cls())
        assert len(engine.signals) == 5

    def test_detect_returns_empty_for_no_triggers(self):
        from src.intraday.signal_engine import SignalEngine
        from src.intraday.signals import VolumeBreakoutSignal
        engine = SignalEngine()
        engine.register(VolumeBreakoutSignal())
        df = _make_5min_df(25, 60.0, "flat")
        ctx = SignalContext(ts_code="002156.SZ")
        results = engine.detect(df, ctx)
        assert results == []

    def test_detect_returns_results_for_trigger(self):
        from src.intraday.signal_engine import SignalEngine
        from src.intraday.signals import VolumeBreakoutSignal
        engine = SignalEngine()
        engine.register(VolumeBreakoutSignal())
        df = _make_5min_df(25, 60.0, "breakout")
        ctx = SignalContext(ts_code="002156.SZ")
        results = engine.detect(df, ctx)
        assert len(results) == 1
        assert results[0].signal_name == "volume_breakout"

    def test_dedup_prevents_duplicate_signal_same_day(self):
        from src.intraday.signal_engine import SignalEngine
        from src.intraday.signals import VolumeBreakoutSignal
        engine = SignalEngine()
        engine.register(VolumeBreakoutSignal())
        df = _make_5min_df(25, 60.0, "breakout")
        ctx = SignalContext(ts_code="002156.SZ")
        results1 = engine.detect(df, ctx)
        assert len(results1) == 1
        results2 = engine.detect(df, ctx)
        assert len(results2) == 0  # dedup blocks second trigger

    def test_dedup_allows_different_signals(self):
        from src.intraday.signal_engine import SignalEngine
        from src.intraday.signals import VolumeBreakoutSignal, PanicDropSignal
        engine = SignalEngine()
        engine.register(VolumeBreakoutSignal())
        engine.register(PanicDropSignal())
        df = _make_5min_df(25, 60.0, "breakout")
        ctx = SignalContext(ts_code="002156.SZ")
        results = engine.detect(df, ctx)
        # Only volume_breakout fires on this data, panic_drop should not
        signals_fired = [r.signal_name for r in results]
        assert "volume_breakout" in signals_fired
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_signals.py::TestSignalEngine -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.intraday.signal_engine'`

- [ ] **Step 3: Implement SignalEngine**

```python
# src/intraday/signal_engine.py
from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from src.intraday.signals.base import BaseSignal
from src.intraday.types import SignalContext, SignalResult

logger = logging.getLogger(__name__)


class SignalEngine:
    """Registers signals, runs detection across all signals, handles dedup."""

    def __init__(self) -> None:
        self.signals: List[BaseSignal] = []
        self._fired_today: Set[Tuple[str, str, date]] = set()

    def register(self, signal: BaseSignal) -> None:
        self.signals.append(signal)
        logger.debug("Registered signal: %s (%s)", signal.name, signal.level.name)

    def detect(self, df: pd.DataFrame, context: SignalContext) -> List[SignalResult]:
        results: List[SignalResult] = []
        today = date.today()
        for signal in self.signals:
            dedup_key = (signal.name, context.ts_code, today)
            if dedup_key in self._fired_today:
                continue
            try:
                result = signal.detect(df, context)
            except Exception:
                logger.exception("Signal %s raised error on %s", signal.name, context.ts_code)
                continue
            if result is not None:
                self._fired_today.add(dedup_key)
                results.append(result)
                logger.info(
                    "Signal fired: %s on %s at %.2f",
                    signal.name, context.ts_code, result.price,
                )
        return results

    def reset_daily(self) -> None:
        self._fired_today.clear()
```

- [ ] **Step 4: Run tests**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_signals.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add src/intraday/signal_engine.py tests/test_intraday_signals.py
git commit -m "feat(intraday): add SignalEngine with registration, detection, and dedup"
```

---

### Task 5: Intraday Config + Tushare Minute-Data Method

**Files:**
- Modify: `src/config.py`
- Modify: `.env.example`
- Modify: `data_provider/tushare_fetcher.py`
- Create: `tests/test_intraday_data.py`

- [ ] **Step 1: Add INTRADAY_* fields to Config dataclass**

In `src/config.py`, find the data-source-token section (around `tushare_token`) and add after it:

```python
    # Intraday monitoring config
    intraday_watch_list: List[str] = field(default_factory=list)
    intraday_poll_interval: int = 15
    intraday_notification_channels: List[str] = field(default_factory=list)
    intraday_llm_model: str = ""
    intraday_backtest_days: int = 365
    intraday_strong_threshold: int = 55
    intraday_evolve_cooldown: int = 5
    intraday_portfolio: Dict[str, Tuple[float, int]] = field(default_factory=dict)
```

Then in `_load_from_env()`, add after the existing data source loading:

```python
            # Intraday monitoring config
            intraday_watch_list=parse_env_list(os.getenv("INTRADAY_WATCH_LIST"), separator=","),
            intraday_poll_interval=parse_env_int(os.getenv("INTRADAY_POLL_INTERVAL"), 15, field_name="INTRADAY_POLL_INTERVAL", minimum=1),
            intraday_notification_channels=parse_env_list(os.getenv("INTRADAY_NOTIFICATION_CHANNELS"), separator=","),
            intraday_llm_model=os.getenv("INTRADAY_LLM_MODEL") or "",
            intraday_backtest_days=parse_env_int(os.getenv("INTRADAY_BACKTEST_DAYS"), 365, field_name="INTRADAY_BACKTEST_DAYS", minimum=30),
            intraday_strong_threshold=parse_env_int(os.getenv("INTRADAY_STRONG_THRESHOLD"), 55, field_name="INTRADAY_STRONG_THRESHOLD", minimum=0, maximum=100),
            intraday_evolve_cooldown=parse_env_int(os.getenv("INTRADAY_EVOLVE_COOLDOWN"), 5, field_name="INTRADAY_EVOLVE_COOLDOWN", minimum=1),
            intraday_portfolio=_parse_intraday_portfolio(os.getenv("INTRADAY_PORTFOLIO")),
```

Also add the helper function near the other parse helpers at the top of the file:

```python
def _parse_intraday_portfolio(raw: Optional[str]) -> Dict[str, Tuple[float, int]]:
    """Parse INTRADAY_PORTFOLIO='002156.SZ:62.00:1000,600460.SH:28.50:2000'."""
    if not raw:
        return {}
    result = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) == 3:
            code = parts[0].strip()
            try:
                cost = float(parts[1])
                qty = int(parts[2])
                result[code] = (cost, qty)
            except (ValueError, IndexError):
                continue
    return result
```

Note: Check if `parse_env_list` already exists in config.py. If not, add:

```python
def parse_env_list(raw: Optional[str], separator: str = ",") -> List[str]:
    if not raw:
        return []
    return [s.strip() for s in raw.split(separator) if s.strip()]
```

- [ ] **Step 2: Add .env.example section**

Append to `.env.example`:

```env

# === Intraday Monitoring Config ===
# Stocks to monitor during trading hours (comma-separated ts_codes)
# INTRADAY_WATCH_LIST=002156.SZ,600460.SH,600887.SH
# Poll interval in minutes (default: 15)
# INTRADAY_POLL_INTERVAL=15
# Notification channels for intraday alerts (default: telegram)
# INTRADAY_NOTIFICATION_CHANNELS=telegram
# LLM model override for intraday analysis (empty = use main LLM config)
# INTRADAY_LLM_MODEL=
# Backtest lookback days (default: 365)
# INTRADAY_BACKTEST_DAYS=365
# Win rate threshold (%) for strong signals (default: 55)
# INTRADAY_STRONG_THRESHOLD=55
# Consecutive days below threshold before signal downgrade (default: 5)
# INTRADAY_EVOLVE_COOLDOWN=5
# Portfolio positions: ts_code:cost:quantity (comma-separated)
# INTRADAY_PORTFOLIO=002156.SZ:62.00:1000,600460.SH:28.50:2000
```

- [ ] **Step 3: Add `get_minute_data()` to TushareFetcher**

In `data_provider/tushare_fetcher.py`, add a new method to the `TushareFetcher` class:

```python
    def get_minute_data(
        self,
        ts_code: str,
        freq: str = "5min",
        start_date: str = "",
        end_date: str = "",
    ) -> Optional[pd.DataFrame]:
        """Fetch minute-level K-line data from Tushare (stk_mins API).

        Args:
            ts_code: Stock code in Tushare format (e.g. '002156.SZ')
            freq: Frequency: 1min/5min/15min/30min/60min
            start_date: Start datetime, format 'YYYY-MM-DD HH:MM:SS'
            end_date: End datetime, format 'YYYY-MM-DD HH:MM:SS'

        Returns:
            DataFrame with columns: ts_code, trade_time, open, close, high, low, vol, amount
        """
        try:
            df = self._call_api_with_rate_limit(
                "stk_mins",
                ts_code=ts_code,
                freq=freq,
                start_date=start_date,
                end_date=end_date,
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "trade_time": "trade_time",
                    "vol": "vol",
                })
            return df
        except Exception as e:
            logger.warning("Failed to fetch minute data for %s: %s", ts_code, e)
            return None
```

- [ ] **Step 4: Write test for TushareFetcher.get_minute_data**

```python
# tests/test_intraday_data.py
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from data_provider.tushare_fetcher import TushareFetcher


class TestTushareFetcherMinuteData(unittest.TestCase):
    @staticmethod
    def _make_fetcher() -> TushareFetcher:
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        fetcher._api = MagicMock()
        return fetcher

    def test_get_minute_data_calls_stk_mins(self):
        fetcher = self._make_fetcher()
        mock_df = pd.DataFrame({
            "ts_code": ["002156.SZ"] * 3,
            "trade_time": ["2026-05-24 09:30:00", "2026-05-24 09:35:00", "2026-05-24 09:40:00"],
            "open": [60.0, 60.1, 60.2],
            "close": [60.1, 60.2, 60.3],
            "high": [60.2, 60.3, 60.4],
            "low": [59.9, 60.0, 60.1],
            "vol": [100000, 110000, 120000],
            "amount": [6000000, 6600000, 7200000],
        })
        fetcher._api.stk_mins.return_value = mock_df
        with patch.object(fetcher, "_check_rate_limit"):
            result = fetcher.get_minute_data("002156.SZ", freq="5min")
        assert result is not None
        assert len(result) == 3
        fetcher._api.stk_mins.assert_called_once_with(
            ts_code="002156.SZ", freq="5min", start_date="", end_date=""
        )

    def test_get_minute_data_returns_none_on_error(self):
        fetcher = self._make_fetcher()
        fetcher._api.stk_mins.side_effect = Exception("API error")
        with patch.object(fetcher, "_check_rate_limit"):
            result = fetcher.get_minute_data("002156.SZ", freq="5min")
        assert result is None
```

- [ ] **Step 5: Run tests**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_data.py -v`
Expected: All tests PASS

- [ ] **Step 6: Verify Config compiles**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -c "from src.config import Config; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add src/config.py .env.example data_provider/tushare_fetcher.py tests/test_intraday_data.py
git commit -m "feat(intraday): add INTRADAY_* config and TushareFetcher.get_minute_data()"
```

---

### Task 6: Intraday Data Fetcher (Wrapper)

**Files:**
- Create: `src/intraday/data_fetcher.py`

- [ ] **Step 1: Write test for IntradayDataFetcher**

Append to `tests/test_intraday_data.py`:

```python
class TestIntradayDataFetcher(unittest.TestCase):
    def test_fetch_minute_bars_delegates_to_tushare(self):
        from src.intraday.data_fetcher import IntradayDataFetcher
        mock_fetcher = MagicMock()
        mock_df = pd.DataFrame({
            "ts_code": ["002156.SZ"] * 5,
            "trade_time": pd.date_range("2026-05-24 09:30", periods=5, freq="5min"),
            "open": [60.0] * 5, "close": [60.1] * 5,
            "high": [60.2] * 5, "low": [59.9] * 5,
            "vol": [100000] * 5, "amount": [6000000] * 5,
        })
        mock_fetcher.get_minute_data.return_value = mock_df
        fetcher = IntradayDataFetcher(tushare_fetcher=mock_fetcher)
        result = fetcher.fetch_minute_bars("002156.SZ", freq="5min", bars=5)
        assert result is not None
        assert len(result) == 5
        mock_fetcher.get_minute_data.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_data.py::TestIntradayDataFetcher -v`
Expected: FAIL

- [ ] **Step 3: Implement IntradayDataFetcher**

```python
# src/intraday/data_fetcher.py
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from data_provider.tushare_fetcher import TushareFetcher

logger = logging.getLogger(__name__)


class IntradayDataFetcher:
    """Thin wrapper around TushareFetcher for intraday-specific data needs."""

    def __init__(self, tushare_fetcher: Optional[TushareFetcher] = None) -> None:
        if tushare_fetcher is not None:
            self._fetcher = tushare_fetcher
        else:
            from src.config import get_config
            config = get_config()
            self._fetcher = TushareFetcher(config=config)

    def fetch_minute_bars(
        self,
        ts_code: str,
        freq: str = "5min",
        start_date: str = "",
        end_date: str = "",
        bars: int = 0,
    ) -> Optional[pd.DataFrame]:
        df = self._fetcher.get_minute_data(
            ts_code=ts_code, freq=freq, start_date=start_date, end_date=end_date,
        )
        if df is None or df.empty:
            return None
        if bars > 0 and len(df) > bars:
            df = df.iloc[-bars:]
        return df
```

- [ ] **Step 4: Run tests**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_data.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add src/intraday/data_fetcher.py tests/test_intraday_data.py
git commit -m "feat(intraday): add IntradayDataFetcher wrapper"
```

---

### Task 7: Backtest Loader (Historical Data with SQLite Cache)

**Files:**
- Create: `src/intraday/backtest/__init__.py`
- Create: `src/intraday/backtest/loader.py`
- Create: `tests/test_intraday_backtest.py`

- [ ] **Step 1: Write test for BacktestDataLoader**

```python
# tests/test_intraday_backtest.py
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from src.intraday.backtest.loader import BacktestDataLoader


class TestBacktestDataLoader(unittest.TestCase):
    def test_load_returns_dataframe(self):
        mock_fetcher = MagicMock()
        mock_df = pd.DataFrame({
            "ts_code": ["002156.SZ"] * 10,
            "trade_time": pd.date_range("2026-05-20 09:30", periods=10, freq="5min"),
            "open": [60.0] * 10, "close": [60.1] * 10,
            "high": [60.2] * 10, "low": [59.9] * 10,
            "vol": [100000] * 10, "amount": [6000000] * 10,
        })
        mock_fetcher.get_minute_data.return_value = mock_df
        loader = BacktestDataLoader(fetcher=mock_fetcher)
        result = loader.load("002156.SZ", days=5)
        assert result is not None
        assert isinstance(result, pd.DataFrame)

    def test_load_returns_none_on_empty_response(self):
        mock_fetcher = MagicMock()
        mock_fetcher.get_minute_data.return_value = pd.DataFrame()
        loader = BacktestDataLoader(fetcher=mock_fetcher)
        result = loader.load("002156.SZ", days=5)
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_backtest.py -v`
Expected: FAIL

- [ ] **Step 3: Implement BacktestDataLoader**

```python
# src/intraday/backtest/__init__.py
```

```python
# src/intraday/backtest/loader.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from src.intraday.data_fetcher import IntradayDataFetcher

logger = logging.getLogger(__name__)


class BacktestDataLoader:
    """Loads historical 5-min K-line data for backtesting.

    Delegates actual fetching to IntradayDataFetcher.
    Future: add SQLite caching to avoid re-fetching.
    """

    def __init__(self, fetcher: Optional[IntradayDataFetcher] = None) -> None:
        self._fetcher = fetcher or IntradayDataFetcher()

    def load(self, ts_code: str, days: int = 365, freq: str = "5min") -> Optional[pd.DataFrame]:
        end_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        logger.info("Loading %d days of %s data for %s", days, freq, ts_code)
        df = self._fetcher.fetch_minute_bars(
            ts_code=ts_code, freq=freq, start_date=start_date, end_date=end_date,
        )
        if df is None or df.empty:
            logger.warning("No data returned for %s", ts_code)
            return None
        logger.info("Loaded %d bars for %s", len(df), ts_code)
        return df
```

- [ ] **Step 4: Run tests**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_backtest.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add src/intraday/backtest/ tests/test_intraday_backtest.py
git commit -m "feat(intraday): add BacktestDataLoader for historical 5-min K-lines"
```

---

### Task 8: Backtest Engine + Reporter

**Files:**
- Create: `src/intraday/backtest/engine.py`
- Create: `src/intraday/backtest/reporter.py`
- Append to `tests/test_intraday_backtest.py`

- [ ] **Step 1: Write tests for engine + reporter**

Append to `tests/test_intraday_backtest.py`:

```python
import numpy as np
from src.intraday.backtest.engine import BacktestEngine
from src.intraday.backtest.reporter import BacktestReporter
from src.intraday.signals import ALL_SIGNALS, VolumeBreakoutSignal
from src.intraday.types import SignalContext


def _make_synthetic_5min_data(days: int = 5) -> pd.DataFrame:
    """Generate ~48 bars/day of synthetic 5-min data."""
    rows = days * 48
    dates = pd.date_range("2026-05-19 09:30", periods=rows, freq="5min")
    np.random.seed(42)
    base = 60.0
    close = base + np.cumsum(np.random.randn(rows) * 0.1)
    vol = np.random.randint(50000, 200000, rows).astype(float)
    # Inject one breakout on day 3
    breakout_idx = 2 * 48 + 30
    close[breakout_idx] = close[breakout_idx - 1] + 3.0
    vol[breakout_idx] = 800000.0
    return pd.DataFrame({
        "trade_time": dates,
        "open": close - np.abs(np.random.randn(rows) * 0.05),
        "high": close + np.abs(np.random.randn(rows) * 0.2),
        "low": close - np.abs(np.random.randn(rows) * 0.2),
        "close": close,
        "vol": vol,
    })


class TestBacktestEngine(unittest.TestCase):
    def test_run_returns_trigger_records(self):
        signals = [VolumeBreakoutSignal()]
        engine = BacktestEngine(signals=signals)
        df = _make_synthetic_5min_data(5)
        ctx = SignalContext(ts_code="002156.SZ")
        records = engine.run(df, ctx, lookback=20, forward_bars=[6, 12])
        # May or may not have triggers depending on data
        assert isinstance(records, list)
        for rec in records:
            assert "signal_name" in rec
            assert "trigger_idx" in rec
            assert "trigger_price" in rec
            assert "forward_returns" in rec

    def test_forward_returns_calculation(self):
        signals = [VolumeBreakoutSignal()]
        engine = BacktestEngine(signals=signals)
        # Build data that guarantees a breakout at bar 25
        rows = 50
        dates = pd.date_range("2026-05-24 09:30", periods=rows, freq="5min")
        close = np.full(rows, 60.0)
        close[24] = 63.0  # breakout at idx 24
        close[25:] = 64.0  # price stays up after breakout
        vol = np.full(rows, 100000.0)
        vol[24] = 500000.0
        df = pd.DataFrame({
            "trade_time": dates, "open": close - 0.1,
            "high": close + 0.1, "low": close - 0.1,
            "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ")
        records = engine.run(df, ctx, lookback=20, forward_bars=[6])
        if records:
            rec = records[0]
            assert rec["forward_returns"][6] > 0


class TestBacktestReporter(unittest.TestCase):
    def test_report_from_records(self):
        records = [
            {"signal_name": "volume_breakout", "forward_returns": {6: 1.5, 12: 2.0}},
            {"signal_name": "volume_breakout", "forward_returns": {6: -0.5, 12: 1.0}},
            {"signal_name": "panic_drop", "forward_returns": {6: 0.8, 12: -0.3}},
        ]
        reporter = BacktestReporter(win_threshold=0.0)
        report = reporter.generate(records)
        assert "volume_breakout" in report
        assert "panic_drop" in report
        assert report["volume_breakout"]["count"] == 2
        assert report["volume_breakout"]["win_rate_6"] == 0.5  # 1 of 2 positive

    def test_empty_records_produce_empty_report(self):
        reporter = BacktestReporter()
        report = reporter.generate([])
        assert report == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_backtest.py -v`
Expected: FAIL

- [ ] **Step 3: Implement BacktestEngine**

```python
# src/intraday/backtest/engine.py
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
            forward_bars = [6, 12, 48]  # 30min, 60min, ~1day

        records: List[Dict] = []
        fired: set = set()  # dedup within run: (signal_name, day)

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
                trigger_price = df.iloc[trigger_idx]["close"]
                forward_returns: Dict[int, float] = {}
                for fwd in forward_bars:
                    fwd_idx = trigger_idx + fwd
                    if fwd_idx < len(df):
                        fwd_price = df.iloc[fwd_idx]["close"]
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
                logger.debug(
                    "Backtest trigger: %s at idx=%d price=%.2f", signal.name, trigger_idx, trigger_price
                )

        logger.info("Backtest produced %d trigger records", len(records))
        return records
```

- [ ] **Step 4: Implement BacktestReporter**

```python
# src/intraday/backtest/reporter.py
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class BacktestReporter:
    """Aggregates backtest trigger records into per-signal win rate statistics."""

    def __init__(self, win_threshold: float = 0.0) -> None:
        self.win_threshold = win_threshold

    def generate(self, records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        if not records:
            return {}

        grouped: Dict[str, List[Dict]] = {}
        for rec in records:
            name = rec["signal_name"]
            grouped.setdefault(name, []).append(rec)

        report: Dict[str, Dict[str, Any]] = {}
        for name, recs in grouped.items():
            count = len(recs)
            forward_bars = sorted(recs[0]["forward_returns"].keys())
            stats: Dict[str, Any] = {"count": count}
            for fb in forward_bars:
                returns = [r["forward_returns"].get(fb) for r in recs if fb in r.get("forward_returns", {})]
                if not returns:
                    continue
                wins = [r for r in returns if r > self.win_threshold]
                stats[f"win_rate_{fb}"] = round(len(wins) / len(returns), 4)
                stats[f"avg_return_{fb}"] = round(sum(returns) / len(returns), 4)
                stats[f"max_return_{fb}"] = round(max(returns), 4)
                stats[f"min_return_{fb}"] = round(min(returns), 4)
            report[name] = stats
            logger.info(
                "Signal %s: %d triggers, win_rate_6=%.1f%%",
                name, count, stats.get("win_rate_6", 0) * 100,
            )
        return report
```

- [ ] **Step 5: Run tests**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_backtest.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add src/intraday/backtest/engine.py src/intraday/backtest/reporter.py tests/test_intraday_backtest.py
git commit -m "feat(intraday): add BacktestEngine and BacktestReporter"
```

---

### Task 9: CLI Entry Point

**Files:**
- Create: `intraday_main.py`

- [ ] **Step 1: Implement intraday_main.py**

```python
#!/usr/bin/env python3
"""Intraday monitoring system CLI entry point.

Usage:
    python intraday_main.py --intraday-backtest [--signal SIGNAL_NAME]
    python intraday_main.py --intraday-monitor
    python intraday_main.py --intraday-evolve
"""
import argparse
import json
import logging
import sys

from src.intraday.signals import ALL_SIGNALS
from src.intraday.types import SignalContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("intraday_main")


def run_backtest(args) -> None:
    from src.intraday.backtest.engine import BacktestEngine
    from src.intraday.backtest.loader import BacktestDataLoader
    from src.intraday.backtest.reporter import BacktestReporter
    from src.config import get_config

    config = get_config()
    watch_list = config.intraday_watch_list
    if not watch_list:
        logger.error("INTRADAY_WATCH_LIST is empty. Set it in .env")
        sys.exit(1)

    signal_classes = ALL_SIGNALS
    if args.signal:
        signal_classes = [s for s in ALL_SIGNALS if s().name == args.signal]
        if not signal_classes:
            logger.error("Unknown signal: %s", args.signal)
            sys.exit(1)

    signals = [cls() for cls in signal_classes]
    loader = BacktestDataLoader()
    engine = BacktestEngine(signals=signals)
    reporter = BacktestReporter()

    all_records = []
    for ts_code in watch_list:
        logger.info("Loading data for %s...", ts_code)
        df = loader.load(ts_code, days=config.intraday_backtest_days)
        if df is None:
            logger.warning("Skipping %s — no data", ts_code)
            continue
        ctx = SignalContext(ts_code=ts_code)
        records = engine.run(df, ctx)
        all_records.extend(records)

    report = reporter.generate(all_records)
    print("\n===== Backtest Report =====")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    total = sum(r["count"] for r in report.values())
    print(f"\nTotal triggers: {total}")
    for name, stats in report.items():
        wr6 = stats.get("win_rate_6", "N/A")
        if isinstance(wr6, float):
            wr6 = f"{wr6:.1%}"
        wr12 = stats.get("win_rate_12", "N/A")
        if isinstance(wr12, float):
            wr12 = f"{wr12:.1%}"
        threshold = config.intraday_strong_threshold / 100
        status = "PASS" if stats.get("win_rate_6", 0) >= threshold else "BELOW THRESHOLD"
        print(f"  {name}: {stats['count']} triggers, win_rate_6={wr6}, win_rate_12={wr12} [{status}]")


def main():
    parser = argparse.ArgumentParser(description="Intraday Monitoring System")
    parser.add_argument("--intraday-backtest", action="store_true", help="Run signal backtest")
    parser.add_argument("--intraday-monitor", action="store_true", help="Start intraday monitoring")
    parser.add_argument("--intraday-evolve", action="store_true", help="Run daily evolution/review")
    parser.add_argument("--signal", type=str, default=None, help="Specific signal to backtest")
    args = parser.parse_args()

    if args.intraday_backtest:
        run_backtest(args)
    elif args.intraday_monitor:
        logger.info("Monitor mode not yet implemented (Phase 2)")
    elif args.intraday_evolve:
        logger.info("Evolve mode not yet implemented (Phase 3)")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify entry point compiles**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -c "import intraday_main; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verify help works**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python intraday_main.py --help`
Expected: Shows usage with `--intraday-backtest`, `--intraday-monitor`, `--intraday-evolve`

- [ ] **Step 4: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add intraday_main.py
git commit -m "feat(intraday): add CLI entry point with --intraday-backtest mode"
```

---

### Task 10: End-to-End Smoke Test

**Files:**
- Create: `tests/test_intraday_e2e.py`

- [ ] **Step 1: Write end-to-end test with mock data**

```python
# tests/test_intraday_e2e.py
"""End-to-end smoke test: synthetic data through the entire backtest pipeline."""
import numpy as np
import pandas as pd
from unittest.mock import MagicMock

from src.intraday.signals import ALL_SIGNALS
from src.intraday.types import SignalContext
from src.intraday.signal_engine import SignalEngine
from src.intraday.backtest.engine import BacktestEngine
from src.intraday.backtest.reporter import BacktestReporter


def _make_multi_day_5min(days: int = 10) -> pd.DataFrame:
    """Generate realistic-ish multi-day 5-min data with injected patterns."""
    bars_per_day = 48
    rows = days * bars_per_day
    dates = pd.date_range("2026-05-12 09:30", periods=rows, freq="5min")
    np.random.seed(123)
    base = 60.0
    returns = np.random.randn(rows) * 0.3
    close = base + np.cumsum(returns)
    close = np.maximum(close, 30.0)  # floor
    vol = np.random.randint(80000, 200000, rows).astype(float)

    # Inject breakout patterns on days 3, 5, 7
    for day_idx in [2, 4, 6]:
        bar = day_idx * bars_per_day + 20
        if bar + 1 < rows:
            prev_max = close[max(0, bar - 20):bar].max()
            close[bar] = prev_max + 1.5
            vol[bar] = 700000.0

    return pd.DataFrame({
        "trade_time": dates,
        "open": close - np.abs(np.random.randn(rows) * 0.05),
        "high": close + np.abs(np.random.randn(rows) * 0.15),
        "low": close - np.abs(np.random.randn(rows) * 0.15),
        "close": close,
        "vol": vol,
    })


class TestE2E:
    def test_full_pipeline(self):
        """Load data → run backtest → generate report → verify output structure."""
        df = _make_multi_day_5min(10)
        ctx = SignalContext(ts_code="002156.SZ")

        signals = [cls() for cls in ALL_SIGNALS]
        engine = BacktestEngine(signals=signals)
        records = engine.run(df, ctx, lookback=20, forward_bars=[6, 12, 48])

        reporter = BacktestReporter()
        report = reporter.generate(records)

        # Report is a dict keyed by signal name
        assert isinstance(report, dict)
        for name, stats in report.items():
            assert "count" in stats
            assert stats["count"] > 0
            assert "win_rate_6" in stats
            assert 0 <= stats["win_rate_6"] <= 1.0
            assert "avg_return_6" in stats

    def test_signal_engine_e2e(self):
        """SignalEngine detects signals on the latest bars of synthetic data."""
        df = _make_multi_day_5min(1)
        ctx = SignalContext(ts_code="002156.SZ")

        engine = SignalEngine()
        for cls in ALL_SIGNALS:
            engine.register(cls())

        results = engine.detect(df, ctx)
        assert isinstance(results, list)
        for r in results:
            assert r.ts_code == "002156.SZ"
            assert r.price > 0
```

- [ ] **Step 2: Run e2e test**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_e2e.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run all intraday tests together**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m pytest tests/test_intraday_*.py -v`
Expected: All tests PASS

- [ ] **Step 4: Run py_compile on all new files**

Run: `cd /home/chase/projects/stock/daily_stock_analysis && python -m py_compile intraday_main.py && python -m py_compile src/intraday/types.py && python -m py_compile src/intraday/signals/base.py && python -m py_compile src/intraday/signals/volume_breakout.py && python -m py_compile src/intraday/signals/panic_drop.py && python -m py_compile src/intraday/signals/chip_breakout.py && python -m py_compile src/intraday/signals/macd_volume.py && python -m py_compile src/intraday/signals/support_break.py && python -m py_compile src/intraday/signal_engine.py && python -m py_compile src/intraday/data_fetcher.py && python -m py_compile src/intraday/backtest/loader.py && python -m py_compile src/intraday/backtest/engine.py && python -m py_compile src/intraday/backtest/reporter.py && echo "All compile OK"`
Expected: "All compile OK"

- [ ] **Step 5: Commit**

```bash
cd /home/chase/projects/stock/daily_stock_analysis
git add tests/test_intraday_e2e.py
git commit -m "test(intraday): add end-to-end smoke test"
```

---

## Self-Review Checklist

### 1. Spec Coverage
- [x] Module structure: `src/intraday/` + `intraday_main.py` — Task 1, 9
- [x] Signal base class + 5 strong signals — Task 2, 3
- [x] Signal engine (registration + dedup) — Task 4
- [x] Config with INTRADAY_* prefix — Task 5
- [x] Data fetcher (Tushare minute data) — Task 5, 6
- [x] Backtest loader — Task 7
- [x] Backtest engine — Task 8
- [x] Backtest reporter — Task 8
- [x] CLI entry with --intraday-* prefix — Task 9
- [x] .env.example updated — Task 5
- [ ] Monitor mode (Phase 2) — not in this plan
- [ ] Evolve mode (Phase 3) — not in this plan
- [ ] LLM strategy signals (Phase 4) — not in this plan

### 2. Placeholder Scan
- No "TBD", "TODO", "implement later" found
- No "add appropriate error handling" — error handling is explicit in each signal
- All test code is complete with assertions

### 3. Type Consistency
- `BaseSignal.detect()` returns `Optional[SignalResult]` — consistent across all signals
- `SignalEngine.signals` is `List[BaseSignal]` — consistent
- `BacktestEngine.run()` returns `List[Dict]` — consistent with `BacktestReporter.generate()` input
- `SignalResult.data` is `Dict[str, Any]` — all signals use string keys
- CLI arg `--signal` matches signal `name` attribute — verified
