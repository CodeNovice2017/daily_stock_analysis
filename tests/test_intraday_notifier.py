"""Tests for intraday notifier formatting."""
from datetime import datetime
from unittest.mock import MagicMock

from src.intraday.notifier import format_signal_message, format_daily_summary, IntradayNotifier
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
        assert "002156.SZ" in msg
        assert "62.35" in msg
        assert "10:45" in msg

    def test_simulation_label(self):
        result = _make_result()
        msg = format_signal_message(result, simulation=True)
        assert "模拟盘" in msg


class TestIntradayNotifier:
    def test_notify_strong_sends_message(self):
        mock_ns = MagicMock()
        notifier = IntradayNotifier(notification_service=mock_ns)
        result = _make_result()
        notifier.notify(result, stock_name="通富微电")
        mock_ns.send_with_results.assert_called_once()

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


class TestFormatDailySummary:
    def test_summary_format(self):
        stats = {
            "trade_date": "2026-05-24",
            "total_signals": 3,
            "by_signal": {"volume_breakout": 2, "panic_drop": 1},
            "by_ts_code": {"002156.SZ": 3},
        }
        msg = format_daily_summary(stats)
        assert "2026-05-24" in msg
        assert "volume_breakout" in msg
