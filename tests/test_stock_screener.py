# -*- coding: utf-8 -*-
"""涨停余温扫描器单元测试。"""

import pytest
from datetime import date

from src.stock_screener.engine import (
    LimitUpReference,
    TrackingDay,
    classify_board,
    evaluate,
    is_limit_up,
)


# ---------------------------------------------------------------------------
# classify_board
# ---------------------------------------------------------------------------

class TestClassifyBoard:
    @pytest.mark.parametrize("code,expected", [
        ("000001", "main"),
        ("600519", "main"),
        ("300750", "gem"),
        ("301000", "gem"),
        ("688001", "star"),
        ("830001", "bse"),
        ("900001", "bse"),
    ])
    def test_classify(self, code, expected):
        assert classify_board(code) == expected


# ---------------------------------------------------------------------------
# is_limit_up
# ---------------------------------------------------------------------------

class TestIsLimitUp:
    def test_main_board_limit_up(self):
        assert is_limit_up(10.0, board_type="main") is True
        assert is_limit_up(9.5, board_type="main") is True
        assert is_limit_up(8.0, board_type="main") is False

    def test_gem_board_limit_up(self):
        assert is_limit_up(20.0, board_type="gem") is True
        assert is_limit_up(15.0, board_type="gem") is False

    def test_code_based_detection(self):
        assert is_limit_up(20.0, code="300750") is True   # gem: 20% threshold
        assert is_limit_up(20.0, code="688001") is True   # star: 20% threshold
        assert is_limit_up(10.0, code="000001") is True   # main: 10% threshold
        assert is_limit_up(10.0, code="300750") is False  # gem needs 20%


# ---------------------------------------------------------------------------
# evaluate - 三条件评估
# ---------------------------------------------------------------------------

def _ref(close=10.0, high=10.5, volume=100000.0, **kwargs):
    return LimitUpReference(close=close, high=high, volume=volume, **kwargs)


def _day(close, high, volume, d="2025-01-02"):
    return TrackingDay(date=d, close=close, high=high, volume=volume)


class TestEvaluate:
    def test_all_three_pass(self):
        ref = _ref(close=10.0, high=10.5, volume=100000.0)
        days = [
            _day(10.2, 10.8, 70000, "2025-01-02"),
            _day(10.1, 10.7, 60000, "2025-01-03"),
            _day(10.3, 10.9, 55000, "2025-01-06"),
        ]
        result = evaluate(ref, days)
        assert result.qualified is True
        assert result.conditions_met == 3
        assert result.score >= 68

    def test_two_of_three_pass(self):
        ref = _ref(close=10.0, high=10.5, volume=100000.0)
        days = [
            _day(9.8, 10.3, 70000, "2025-01-02"),   # price OK, no new high
            _day(9.7, 10.6, 60000, "2025-01-03"),   # price OK, new high
            _day(10.1, 10.8, 55000, "2025-01-06"),  # price OK, new high, volume OK
        ]
        result = evaluate(ref, days)
        assert result.qualified is True
        assert result.conditions_met >= 2

    def test_price_fails(self):
        ref = _ref(close=10.0, high=10.5, volume=100000.0)
        days = [
            _day(9.5, 10.6, 70000, "2025-01-02"),   # below 9.7 threshold
            _day(9.8, 10.7, 60000, "2025-01-03"),
            _day(10.1, 10.8, 55000, "2025-01-06"),
        ]
        result = evaluate(ref, days)
        # price_hold fails, but new_highs + volume may pass (2/3)
        assert result.conditions_met >= 1

    def test_insufficient_data(self):
        ref = _ref()
        result = evaluate(ref, [_day(10.0, 10.5, 50000)], expected_days=3)
        assert result.qualified is False
        assert result.should_evaluate is False

    def test_zero_volume_reference(self):
        ref = _ref(volume=0)
        days = [_day(10.0, 10.5, 50000)] * 3
        result = evaluate(ref, days, expected_days=3)
        # volume condition should fail gracefully
        assert result.should_evaluate is True

    def test_volume_out_of_range(self):
        ref = _ref(volume=100000.0)
        days = [
            _day(10.0, 10.6, 20000, "2025-01-02"),   # avg=20000, ratio=0.2 < 0.4
            _day(10.0, 10.6, 20000, "2025-01-03"),
            _day(10.0, 10.6, 20000, "2025-01-06"),
        ]
        result = evaluate(ref, days, expected_days=3)
        vol_cond = [c for c in result.conditions if c.name == "volume"][0]
        assert vol_cond.passed is False

    def test_score_range(self):
        ref = _ref(close=10.0, high=10.5, volume=100000.0)
        # Perfect conditions
        days = [
            _day(10.5, 11.0, 60000, "2025-01-02"),
            _day(10.3, 10.8, 55000, "2025-01-03"),
            _day(10.4, 10.9, 58000, "2025-01-06"),
        ]
        result = evaluate(ref, days)
        assert 68 <= result.score <= 100

    def test_min_conditions_override(self):
        ref = _ref(close=10.0, high=10.5, volume=100000.0, min_conditions=3)
        # Only 2 pass
        days = [
            _day(9.5, 10.3, 70000, "2025-01-02"),   # price fails
            _day(10.0, 10.6, 60000, "2025-01-03"),
            _day(10.1, 10.8, 55000, "2025-01-06"),
        ]
        result = evaluate(ref, days, expected_days=3)
        assert result.qualified is False


class TestVolumeSurgeVeto:
    """单日放量熔断：宁缺毋滥，出货信号一票否决。"""

    def test_single_day_surge_disqualifies(self):
        """即便价格守住+创新高，单日放量 >1.2× 也一票否决。"""
        ref = _ref(close=10.0, high=10.5, volume=100000.0, volume_surge_ratio=1.2)
        days = [
            _day(10.2, 10.8, 130000, "2025-01-02"),   # 单日 1.3× → 出货
            _day(10.3, 10.9, 60000, "2025-01-03"),
            _day(10.4, 11.0, 55000, "2025-01-06"),
        ]
        result = evaluate(ref, days, expected_days=3)
        assert result.qualified is False
        assert "一票否决" in result.summary or "放量" in result.summary

    def test_surge_disabled_when_ratio_zero(self):
        """volume_surge_ratio=0 关闭熔断。"""
        ref = _ref(close=10.0, high=10.5, volume=100000.0, volume_surge_ratio=0)
        days = [
            _day(10.2, 10.8, 200000, "2025-01-02"),   # 2× 放量但熔断关闭
            _day(10.3, 10.9, 60000, "2025-01-03"),
            _day(10.4, 11.0, 55000, "2025-01-06"),
        ]
        result = evaluate(ref, days, expected_days=3)
        # 熔断关闭，按正常三条件评估（量能这组均量会超 1.0，但应不被熔断）
        assert "一票否决" not in result.summary

    def test_boundary_surge_not_triggered(self):
        """单日正好 1.2× 不触发熔断（边界值）。"""
        ref = _ref(close=10.0, high=10.5, volume=100000.0, volume_surge_ratio=1.2)
        days = [
            _day(10.2, 10.8, 120000, "2025-01-02"),   # 正好 1.2×
            _day(10.3, 10.9, 60000, "2025-01-03"),
            _day(10.4, 11.0, 55000, "2025-01-06"),
        ]
        result = evaluate(ref, days, expected_days=3)
        assert "一票否决" not in result.summary


# ---------------------------------------------------------------------------
# Score computation edge cases
# ---------------------------------------------------------------------------

class TestScoreEdgeCases:
    def test_boundary_price_hold(self):
        """Price exactly at threshold."""
        ref = _ref(close=10.0, high=10.5, volume=100000.0)
        days = [
            _day(9.7, 10.6, 60000, "2025-01-02"),   # exactly 97%
            _day(9.7, 10.7, 55000, "2025-01-03"),
            _day(9.7, 10.8, 58000, "2025-01-06"),
        ]
        result = evaluate(ref, days)
        price_cond = [c for c in result.conditions if c.name == "price_hold"][0]
        assert price_cond.passed is True

    def test_boundary_volume(self):
        """Volume exactly at boundaries."""
        ref = _ref(volume=100000.0, volume_low_ratio=0.40, volume_high_ratio=1.20)
        # avg = 40000, ratio = 0.40 (exactly at lower bound)
        days = [_day(10.0, 10.6, 40000, "2025-01-02")] * 3
        result = evaluate(ref, days, expected_days=3)
        vol_cond = [c for c in result.conditions if c.name == "volume"][0]
        assert vol_cond.passed is True
