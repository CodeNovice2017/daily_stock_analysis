# -*- coding: utf-8 -*-
"""[personal patch] P0-1 风控分层表达：软压缩评分与降级文案的单元测试。"""

from __future__ import annotations

import pytest

from src.agent.orchestrator import (
    _risk_downgrade_narrative,
    _soft_adjust_sentiment_score,
)


class TestSoftAdjustSentimentScore:
    """降级软压缩：保留个股间区分度，替代一刀切压档顶。"""

    def test_buy_to_hold_one_step_penalty(self):
        # 一步降 -8，且受 hold 档上限约束
        assert _soft_adjust_sentiment_score(72, "buy", "hold") == 59

    def test_buy_to_hold_low_score_floor(self):
        # 保底不低于 hold 档中值（45）：60-8=52 > 45，不受影响
        assert _soft_adjust_sentiment_score(60, "buy", "hold") == 52

    def test_hold_to_sell_one_step(self):
        # 一步降（58-8=50）超 sell 上限 39 → 压回 39
        assert _soft_adjust_sentiment_score(58, "hold", "sell") == 39

    def test_hold_to_sell_floor_at_midband(self):
        # 低分中性一步降：45-8=37 > sell 中值 20，保留 37（区分度体现）
        assert _soft_adjust_sentiment_score(45, "hold", "sell") == 37

    def test_hold_to_sell_very_low_floor(self):
        # 极低分：30-8=22 > floor 19 → 22；再低也不跌破 19（sell 档中值 (0+39)//2）
        assert _soft_adjust_sentiment_score(30, "hold", "sell") == 22
        assert _soft_adjust_sentiment_score(10, "hold", "sell") == 19

    def test_buy_to_sell_two_step_penalty(self):
        # 两步降 -15：75-15=60 超 sell 上限 → 39
        assert _soft_adjust_sentiment_score(75, "buy", "sell") == 39
        # 低分两步降触发 floor：40-15=25 > 20 → 25
        assert _soft_adjust_sentiment_score(40, "buy", "sell") == 25

    def test_preserves_cross_stock_spread(self):
        # 核心目标：两只同被降级的股票，高分股最终分仍高于低分股
        high = _soft_adjust_sentiment_score(58, "hold", "sell")
        low = _soft_adjust_sentiment_score(45, "hold", "sell")
        assert high > low

    def test_unknown_signal_fallback(self):
        # 未知信号按一步降处理，不抛异常
        result = _soft_adjust_sentiment_score(50, "unknown", "sell")
        assert 20 <= result <= 39


class TestRiskDowngradeNarrative:
    """三分支降级文案：区分"原观点"与"最终建议"。"""

    def test_buy_to_hold_keeps_bullish_view(self):
        text = _risk_downgrade_narrative("buy", "hold", "risk_veto", 72)
        assert "观点仍偏多" in text
        assert "72" in text
        assert "risk_veto" in text

    def test_buy_to_sell_warns_thesis_break(self):
        text = _risk_downgrade_narrative("buy", "sell", "high_severity_flag", 75)
        assert "多头逻辑可能被破坏" in text

    def test_hold_to_sell_defensive_tone(self):
        text = _risk_downgrade_narrative("hold", "sell", "downgrade_one", 58)
        assert "中性" in text
        assert "防守" in text

    def test_none_score_omits_hint(self):
        text = _risk_downgrade_narrative("buy", "hold", "risk_veto", None)
        assert "原评分" not in text

    def test_unknown_transition_generic(self):
        text = _risk_downgrade_narrative("sell", "buy", "other", 10)
        assert "sell" in text and "buy" in text
