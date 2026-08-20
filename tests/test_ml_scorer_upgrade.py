# -*- coding: utf-8 -*-
"""[personal patch] P2：中长线选股器实证因子升级的单元测试。

覆盖：时序 SUE、残差动量（Blitz 标准化）、现金流实现率子因子、
估值降权后的分值结构、单季净利润差分。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from src.ml_agent.screener.data_provider import MLDataProvider
from src.ml_agent.screener.scorer import (
    compute_residual_momentum,
    compute_sue,
    score_growth,
    score_quality,
    score_trend,
)


def _idx_series(values, start="2025-01-02"):
    return pd.Series(
        values,
        index=pd.bdate_range(start, periods=len(values)),
        dtype=float,
    )


def _daily_df(closes, vols=None):
    n = len(closes)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-02", periods=n),
            "close": [float(c) for c in closes],
            "volume": [float(v) for v in (vols or [100.0] * n)],
        }
    )


class TestSue:
    def test_earnings_surprise_scores_high(self):
        quarters = [10.0, 10.0, 10.0, 10.0, 11.0, 10.0, 10.0, 10.0, 18.0]
        sue = compute_sue(quarters)
        assert sue is not None and sue > 1.5

    def test_earnings_miss_scores_negative(self):
        quarters = [10.0, 10.0, 10.0, 10.0, 11.0, 10.0, 10.0, 10.0, 4.0]
        sue = compute_sue(quarters)
        assert sue is not None and sue < -1.5

    def test_insufficient_data_returns_none(self):
        assert compute_sue([1.0, 2.0, 3.0]) is None
        assert compute_sue(None) is None

    def test_zero_variance_returns_none(self):
        # 历史完全平坦（std=0）时无法标准化
        assert compute_sue([5.0] * 9) is None

    def test_growth_dimension_uses_sue(self):
        fina = {"or_yoy": 20.0, "netprofit_yoy": 25.0, "q_profit_yoy": 30.0}
        with_sue, _, _ = score_growth(fina, sue=2.0)
        without, _, _ = score_growth(fina, sue=None)
        assert with_sue > without
        assert with_sue - without == 10  # SUE 满档


class TestResidualMomentum:
    def test_independent_uptrend_positive(self):
        stock = _idx_series([10 * (1.004 ** i) for i in range(150)])  # 独立走强
        market = _idx_series([100.0] * 150)  # 指数横盘
        rm = compute_residual_momentum(stock, market)
        assert rm is not None and rm > 1.0

    def test_pure_beta_exposure_near_zero(self):
        # 个股严格跟随指数（只有 beta 没有残差）→ 残差动量≈0
        market = _idx_series([100 * (1 + 0.001 * ((-1) ** i)) for i in range(150)])
        stock = _idx_series([v / 2 for v in market.values])
        rm = compute_residual_momentum(stock, market)
        assert rm is not None and abs(rm) < 0.3

    def test_independent_downtrend_negative(self):
        stock = _idx_series([10 * (0.996 ** i) for i in range(150)])
        market = _idx_series([100.0] * 150)
        rm = compute_residual_momentum(stock, market)
        assert rm is not None and rm < -1.0

    def test_short_history_returns_none(self):
        stock = _idx_series([10.0] * 30)
        market = _idx_series([100.0] * 30)
        assert compute_residual_momentum(stock, market) is None

    def test_trend_dimension_includes_residual(self):
        closes = [10 * (1.003 ** i) for i in range(180)]
        flat_index = pd.DataFrame(
            {"date": pd.bdate_range("2025-01-02", periods=180), "close": [100.0] * 180}
        )
        with_idx, _, _, detail = score_trend(_daily_df(closes), index_df=flat_index)
        without, _, _, _ = score_trend(_daily_df(closes), index_df=None)
        assert with_idx > without
        assert detail.get("residual_momentum") is not None


class TestCashflowQuality:
    def test_cash_backed_earns_points(self):
        fina = {"roe": 18.0, "grossprofit_margin": 40.0, "netprofit_margin": 15.0, "roe_trend": "up"}
        with_cash, hl, _ = score_quality(fina, cash_ratio=1.5)
        without, _, _ = score_quality(fina, cash_ratio=None)
        assert with_cash - without == 5
        assert any("现金" in h for h in hl)

    def test_poor_cash_conversion_flagged(self):
        fina = {"roe": 18.0, "grossprofit_margin": 40.0, "netprofit_margin": 15.0}
        _, _, risks = score_quality(fina, cash_ratio=0.3)
        assert any("利润质量差" in r for r in risks)


class TestValuationDownweight:
    def test_valuation_max_is_twelve(self):
        # PE/PB 双双极度低估（分位 0.1）
        from src.ml_agent.screener.scorer import score_valuation

        score, hl, _ = score_valuation(pe=10, pb=1.0, pe_percentile=0.1, pb_percentile=0.1)
        assert score == 12
        assert any("极度低估" in h for h in hl)


class TestSingleQuarterDifferencing:
    def _provider_with_income(self, rows):
        dp = object.__new__(MLDataProvider)
        dp._index_daily_cache = None
        dp._fetcher = MagicMock()
        dp._fetcher._convert_stock_code.return_value = "000001.SZ"
        df = pd.DataFrame(rows, columns=["ts_code", "end_date", "n_income"])
        dp._fetcher._call_api_with_rate_limit.return_value = df
        return dp

    def test_cumulative_to_single_quarter(self):
        rows = [
            ("000001.SZ", "20250331", 10.0),   # Q1 = 10
            ("000001.SZ", "20250630", 25.0),   # Q2 = 15
            ("000001.SZ", "20250930", 39.0),   # Q3 = 14
            ("000001.SZ", "20251231", 50.0),   # Q4 = 11
            ("000001.SZ", "20260331", 13.0),   # 新一年 Q1 = 13（不差分）
            ("000001.SZ", "20260630", 30.0),   # Q2 = 17
        ]
        dp = self._provider_with_income(rows)
        quarters = dp.get_single_quarter_profits("000001")
        assert quarters == [10.0, 15.0, 14.0, 11.0, 13.0, 17.0]

    def test_too_few_periods_returns_none(self):
        rows = [("000001.SZ", "20260331", 10.0), ("000001.SZ", "20260630", 25.0)]
        dp = self._provider_with_income(rows)
        assert dp.get_single_quarter_profits("000001") is None


class TestWeightStructure:
    def test_dimension_maxima_sum_to_hundred(self):
        fina = {"roe": 25.0, "grossprofit_margin": 60.0, "netprofit_margin": 30.0, "roe_trend": "up"}
        q_max, _, _ = score_quality(fina, cash_ratio=2.0)
        assert q_max == 30
        g_max, _, _ = score_growth(
            {"or_yoy": 40.0, "netprofit_yoy": 60.0, "q_profit_yoy": 70.0}, sue=2.0
        )
        assert g_max == 28
        from src.ml_agent.screener.scorer import score_valuation

        v_max, _, _ = score_valuation(10, 1.0, 0.1, 0.1)
        assert v_max == 12
        closes = [10 * (1.003 ** i) for i in range(180)]
        flat_index = pd.DataFrame(
            {"date": pd.bdate_range("2025-01-02", periods=180), "close": [100.0] * 180}
        )
        t_max, _, _, _ = score_trend(_daily_df(closes, vols=[100.0] * 180), index_df=flat_index)
        # 趋势满档 = MA6 + 乖离(回踩0-5%给3；单边上行走1-2) + 量能2 + 残差9
        assert t_max <= 20 and t_max >= 17
