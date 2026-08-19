# -*- coding: utf-8 -*-
"""[personal patch] P0-2 观望计分：cash 建议机会成本分类的单元测试。"""

from __future__ import annotations

from src.core.backtest_engine import BacktestEngine, EvaluationConfig


class TestClassifyCashOpportunity:
    """missed_bull / correct_avoid / neutral 三态分类。"""

    def test_cash_missed_bull(self):
        assert (
            BacktestEngine._classify_cash_opportunity(
                stock_return_pct=5.0, position="cash", missed_bull_pct=5.0
            )
            == "missed_bull"
        )

    def test_cash_correct_avoid(self):
        assert (
            BacktestEngine._classify_cash_opportunity(
                stock_return_pct=-6.2, position="cash", missed_bull_pct=5.0
            )
            == "correct_avoid"
        )

    def test_cash_neutral(self):
        assert (
            BacktestEngine._classify_cash_opportunity(
                stock_return_pct=2.0, position="cash", missed_bull_pct=5.0
            )
            == "neutral"
        )

    def test_long_returns_none(self):
        # long 建议已有 win/loss 语义，不参与观望计分
        assert (
            BacktestEngine._classify_cash_opportunity(
                stock_return_pct=10.0, position="long", missed_bull_pct=5.0
            )
            is None
        )

    def test_none_return_returns_none(self):
        assert (
            BacktestEngine._classify_cash_opportunity(
                stock_return_pct=None, position="cash", missed_bull_pct=5.0
            )
            is None
        )

    def test_negative_threshold_abs(self):
        # 阈值取绝对值，负配置不产生怪异区间
        assert (
            BacktestEngine._classify_cash_opportunity(
                stock_return_pct=5.0, position="cash", missed_bull_pct=-5.0
            )
            == "missed_bull"
        )


class TestEvaluationConfigDefault:
    def test_missed_bull_default(self):
        config = EvaluationConfig(eval_window_days=10)
        assert config.missed_bull_pct == 5.0
