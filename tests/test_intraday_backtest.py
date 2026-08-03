"""Tests for intraday backtest engine and reporter."""
import numpy as np
import pandas as pd

from src.intraday.signals import ALL_SIGNALS
from src.intraday.types import SignalContext
from src.intraday.backtest.engine import BacktestEngine
from src.intraday.backtest.reporter import BacktestReporter


def _make_synthetic_5min(days: int = 5) -> pd.DataFrame:
    rows = days * 48
    dates = pd.date_range("2026-05-19 09:30", periods=rows, freq="5min")
    np.random.seed(42)
    base = 60.0
    close = base + np.cumsum(np.random.randn(rows) * 0.1)
    vol = np.random.randint(50000, 200000, rows).astype(float)
    breakout_idx = 2 * 48 + 30
    if breakout_idx < rows:
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


class TestBacktestEngine:
    def test_run_returns_trigger_records(self):
        from src.intraday.signals.volume_breakout import VolumeBreakoutSignal
        engine = BacktestEngine(signals=[VolumeBreakoutSignal()])
        df = _make_synthetic_5min(5)
        ctx = SignalContext(ts_code="002156.SZ")
        records = engine.run(df, ctx, lookback=20, forward_bars=[6, 12])
        assert isinstance(records, list)
        for rec in records:
            assert "signal_name" in rec
            assert "trigger_idx" in rec
            assert "trigger_price" in rec
            assert "forward_returns" in rec


class TestBacktestReporter:
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
        assert report["volume_breakout"]["win_rate_6"] == 0.5

    def test_empty_records(self):
        reporter = BacktestReporter()
        assert reporter.generate([]) == {}
