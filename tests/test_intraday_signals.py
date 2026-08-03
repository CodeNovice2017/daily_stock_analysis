"""Tests for intraday types, signals, and engine."""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from src.intraday.types import SignalLevel, SignalContext, SignalResult
from src.intraday.signals.base import BaseSignal
from src.intraday.signals import ALL_SIGNALS
from src.intraday.signal_engine import SignalEngine


def _make_5min_df(rows: int = 25, base_price: float = 60.0, trend: str = "flat") -> pd.DataFrame:
    np.random.seed(42)
    dates = pd.date_range("2026-05-24 09:30", periods=rows, freq="5min")
    if trend == "flat":
        close = base_price + np.random.randn(rows) * 0.2
    elif trend == "breakout":
        close = np.full(rows, base_price)
        close[-1] = base_price + 2.0
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
        vol[-1] = vol_base * 4.0
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


class TestSignalLevel:
    def test_ordering(self):
        assert SignalLevel.STRONG > SignalLevel.MEDIUM > SignalLevel.WEAK


class TestSignalResult:
    def test_creation(self):
        result = SignalResult(
            signal_name="volume_breakout",
            level=SignalLevel.STRONG,
            triggered_at=datetime(2026, 5, 24, 10, 45),
            ts_code="002156.SZ",
            price=62.35,
            data={"volume_ratio": 3.8},
        )
        assert result.signal_name == "volume_breakout"
        assert result.price == 62.35


class TestVolumeBreakoutSignal:
    def test_fires_on_breakout_with_high_volume(self):
        from src.intraday.signals.volume_breakout import VolumeBreakoutSignal
        signal = VolumeBreakoutSignal()
        df = _make_5min_df(25, 60.0, "breakout")
        ctx = SignalContext(ts_code="002156.SZ")
        result = signal.detect(df, ctx)
        assert result is not None
        assert result.signal_name == "volume_breakout"
        assert result.data["volume_ratio"] > 3.0

    def test_no_fire_without_volume(self):
        from src.intraday.signals.volume_breakout import VolumeBreakoutSignal
        signal = VolumeBreakoutSignal()
        df = _make_5min_df(25, 60.0, "no_volume")
        ctx = SignalContext(ts_code="002156.SZ")
        assert signal.detect(df, ctx) is None

    def test_no_fire_without_breakout(self):
        from src.intraday.signals.volume_breakout import VolumeBreakoutSignal
        signal = VolumeBreakoutSignal()
        df = _make_5min_df(25, 60.0, "flat")
        ctx = SignalContext(ts_code="002156.SZ")
        assert signal.detect(df, ctx) is None

    def test_no_fire_insufficient_data(self):
        from src.intraday.signals.volume_breakout import VolumeBreakoutSignal
        signal = VolumeBreakoutSignal()
        df = _make_5min_df(10, 60.0, "breakout")
        ctx = SignalContext(ts_code="002156.SZ")
        assert signal.detect(df, ctx) is None


class TestPanicDropSignal:
    def test_fires_on_sharp_drop_with_volume(self):
        from src.intraday.signals.panic_drop import PanicDropSignal
        signal = PanicDropSignal()
        dates = pd.date_range("2026-05-24 09:30", periods=10, freq="5min")
        base_price = 60.0
        open_prices = np.full(10, base_price)
        close = np.full(10, base_price)
        close[-1] = base_price * 0.97  # 3% drop within the bar
        vol = np.full(10, 100000.0)
        vol[-1] = 600000.0
        df = pd.DataFrame({
            "trade_time": dates, "open": open_prices, "high": np.maximum(open_prices, close) + 0.1,
            "low": np.minimum(open_prices, close) - 0.1, "close": close, "vol": vol,
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
        close[-1] = 59.5
        vol = np.full(10, 100000.0)
        vol[-1] = 600000.0
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ")
        assert signal.detect(df, ctx) is None


class TestChipBreakoutSignal:
    def test_fires_on_break_above_chip(self):
        from src.intraday.signals.chip_breakout import ChipBreakoutSignal
        signal = ChipBreakoutSignal()
        dates = pd.date_range("2026-05-24 09:30", periods=25, freq="5min")
        close = np.full(25, 60.0)
        close[-1] = 62.0
        vol = np.full(25, 100000.0)
        vol[-1] = 200000.0
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ", chip_cost_95=61.0, avg_daily_volume=100000.0)
        result = signal.detect(df, ctx)
        assert result is not None
        assert result.signal_name == "chip_breakout"

    def test_no_fire_below_chip(self):
        from src.intraday.signals.chip_breakout import ChipBreakoutSignal
        signal = ChipBreakoutSignal()
        dates = pd.date_range("2026-05-24 09:30", periods=25, freq="5min")
        close = np.full(25, 60.0)
        close[-1] = 60.5
        vol = np.full(25, 100000.0)
        vol[-1] = 200000.0
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ", chip_cost_95=61.0, avg_daily_volume=100000.0)
        assert signal.detect(df, ctx) is None


class TestSupportBreakSignal:
    def test_fires_on_break_below_ma_with_volume(self):
        from src.intraday.signals.support_break import SupportBreakSignal
        signal = SupportBreakSignal()
        dates = pd.date_range("2026-05-24 09:30", periods=25, freq="5min")
        close = np.full(25, 58.0)
        close[-1] = 54.0
        vol = np.full(25, 100000.0)
        vol[-1] = 300000.0
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
        dates = pd.date_range("2026-05-24 09:30", periods=25, freq="5min")
        close = np.full(25, 58.0)
        close[-1] = 54.0
        vol = np.full(25, 100000.0)
        df = pd.DataFrame({
            "trade_time": dates, "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "vol": vol,
        })
        ctx = SignalContext(ts_code="002156.SZ", ma20=56.0, ma60=55.0, prev_low=55.5)
        assert signal.detect(df, ctx) is None


class TestSignalEngine:
    def test_register_and_detect_all(self):
        engine = SignalEngine()
        for cls in ALL_SIGNALS:
            engine.register(cls())
        assert len(engine.signals) == 5

    def test_detect_returns_empty_for_no_triggers(self):
        from src.intraday.signals.volume_breakout import VolumeBreakoutSignal
        engine = SignalEngine()
        engine.register(VolumeBreakoutSignal())
        df = _make_5min_df(25, 60.0, "flat")
        ctx = SignalContext(ts_code="002156.SZ")
        assert engine.detect(df, ctx) == []

    def test_detect_returns_results_for_trigger(self):
        from src.intraday.signals.volume_breakout import VolumeBreakoutSignal
        engine = SignalEngine()
        engine.register(VolumeBreakoutSignal())
        df = _make_5min_df(25, 60.0, "breakout")
        ctx = SignalContext(ts_code="002156.SZ")
        results = engine.detect(df, ctx)
        assert len(results) == 1
        assert results[0].signal_name == "volume_breakout"

    def test_dedup_prevents_duplicate(self):
        from src.intraday.signals.volume_breakout import VolumeBreakoutSignal
        engine = SignalEngine()
        engine.register(VolumeBreakoutSignal())
        df = _make_5min_df(25, 60.0, "breakout")
        ctx = SignalContext(ts_code="002156.SZ")
        assert len(engine.detect(df, ctx)) == 1
        assert len(engine.detect(df, ctx)) == 0
