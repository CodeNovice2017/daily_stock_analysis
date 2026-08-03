"""Tests for intraday scheduler trading hours logic."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from src.intraday.scheduler import is_trading_hours


class TestTradingHours:
    def test_morning_trading(self):
        assert is_trading_hours(datetime(2026, 5, 22, 10, 30)) is True

    def test_afternoon_trading(self):
        assert is_trading_hours(datetime(2026, 5, 22, 14, 0)) is True

    def test_lunch_break(self):
        assert is_trading_hours(datetime(2026, 5, 22, 12, 0)) is False

    def test_weekend(self):
        assert is_trading_hours(datetime(2026, 5, 23, 10, 30)) is False

    def test_before_open(self):
        assert is_trading_hours(datetime(2026, 5, 22, 9, 15)) is False

    def test_after_close(self):
        assert is_trading_hours(datetime(2026, 5, 22, 15, 5)) is False

    def test_boundary_open(self):
        assert is_trading_hours(datetime(2026, 5, 22, 9, 30)) is True

    def test_boundary_close(self):
        assert is_trading_hours(datetime(2026, 5, 22, 15, 0)) is True
