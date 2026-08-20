# -*- coding: utf-8 -*-
"""[personal patch] P1-A：get_volume_analysis 量价信号升级的单元测试。

覆盖：vp_corr 语义修复（量 vs 当日涨跌幅）、250日量能分位（地量/天量）、
OBV 顶/底背离、放量突破 vs 高位滞涨出货判别、pattern 位置维度。
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.agent.tools.analysis_tools import _handle_get_volume_analysis


def _mk_df(closes, vols, opens=None, highs=None, lows=None, start="2025-06-02"):
    """构造规范 K 线 DataFrame；open/high/low 缺省按 close ±1% 推导。"""
    closes = list(closes)
    vols = list(vols)
    n = len(closes)
    if opens is None:
        opens = [c * 0.995 for c in closes]
    if highs is None:
        highs = [max(o, c) * 1.01 for o, c in zip(opens, closes)]
    if lows is None:
        lows = [min(o, c) * 0.99 for o, c in zip(opens, closes)]
    return pd.DataFrame(
        {
            "date": pd.bdate_range(start, periods=n),
            "open": [float(x) for x in opens],
            "high": [float(x) for x in highs],
            "low": [float(x) for x in lows],
            "close": [float(x) for x in closes],
            "volume": [float(x) for x in vols],
        }
    )


def _run(df):
    with patch("src.services.history_loader.load_history_df", return_value=(df, "db_cache")):
        return _handle_get_volume_analysis("600519", days=30)


class TestVpCorrSemantics:
    """vp_corr 应为 成交量 vs 当日涨跌幅 的相关（修复旧版被趋势主导的缺陷）。"""

    def test_corr_positive_when_volume_confirms_moves(self):
        # 涨日放量、跌日缩量交替（净横盘）：量与涨跌幅正相关
        closes, vols = [], []
        px = 10.0
        for i in range(60):
            if i % 2 == 0:
                px *= 1.01
                vols.append(200.0)
            else:
                px *= 0.99
                vols.append(100.0)
            closes.append(px)
        result = _run(_mk_df(closes, vols))
        assert result["volume_price_corr"] is not None
        assert result["volume_price_corr"] > 0.5

    def test_corr_absent_when_returns_constant(self):
        # 单边匀速上涨+恒定量能：旧实现 corr(vol, close)≈+1 误导；
        # 新实现涨跌幅方差为 0 → 无有效信号（None），不再输出伪相关
        closes = [10.0 * (1.01 ** i) for i in range(60)]
        vols = [100.0] * 60
        result = _run(_mk_df(closes, vols))
        assert result["volume_price_corr"] is None


class TestVolumePercentile:
    def test_dry_volume_flagged_at_low_percentile(self):
        n = 250
        vols = [100.0] * (n - 1) + [10.0]  # 最新一天为全窗口最小
        closes = [10.0 * (1.001 ** i) for i in range(n)]
        result = _run(_mk_df(closes, vols))
        assert result["volume_percentile"] < 20
        assert result["volume_percentile_label"] == "地量"

    def test_climax_volume_flagged_at_high_percentile(self):
        n = 250
        vols = [100.0] * (n - 1) + [900.0]  # 最新一天为全窗口最大
        closes = [10.0 * (1.001 ** i) for i in range(n)]
        result = _run(_mk_df(closes, vols))
        assert result["volume_percentile"] > 90
        assert result["volume_percentile_label"] == "天量"

    def test_short_history_omits_percentile(self):
        closes = [10.0 + 0.01 * i for i in range(50)]
        vols = [100.0] * 50
        result = _run(_mk_df(closes, vols))
        assert "volume_percentile" not in result


class TestObvDivergence:
    def test_bearish_divergence_price_high_obv_lagging(self):
        # 价格震荡走高创窗口新高，但下跌日量能 3 倍于上涨日 → OBV 滞涨
        closes, vols = [], []
        px = 10.0
        for i in range(121):
            if i % 2 == 0:
                px *= 1.02
                vols.append(100.0)
            else:
                px *= 0.99
                vols.append(300.0)
            closes.append(px)
        result = _run(_mk_df(closes, vols))
        assert result["obv_divergence"] == "bearish"

    def test_bullish_divergence_price_low_obv_holding(self):
        # 价格震荡走低创新低，但上涨日量能 3 倍于下跌日 → 下跌量能衰竭
        closes, vols = [], []
        px = 10.0
        for i in range(121):
            if i % 2 == 0:
                px *= 0.98
                vols.append(100.0)
            else:
                px *= 1.01
                vols.append(300.0)
            closes.append(px)
        result = _run(_mk_df(closes, vols))
        assert result["obv_divergence"] == "bullish"

    def test_no_divergence_when_confirmed(self):
        # 单边放量上涨：价新高且 OBV 同步新高 → 无背离信号
        closes, vols = [], []
        px = 10.0
        for i in range(121):
            px *= 1.01
            closes.append(px)
            vols.append(100.0 + i)
        result = _run(_mk_df(closes, vols))
        assert result.get("obv_divergence") is None


class TestBreakoutAssessment:
    def _base(self):
        # 100 日 10.0 附近横盘，vol 100，区间高点约 10.6
        closes = [10.0 + 0.2 * ((i % 10) - 5) / 5 for i in range(100)]
        vols = [100.0] * 100
        return closes, vols

    def test_valid_breakout(self):
        closes, vols = self._base()
        closes[-1] = 11.1
        result = _run(
            _mk_df(
                closes,
                vols[:-1] + [500.0],
                opens=None,
                highs=[max(a, b) * 1.002 for a, b in zip(closes, closes)][:-1] + [11.2],
                lows=[min(a, b) * 0.998 for a, b in zip(closes, closes)][:-1] + [10.3],
            )
        )
        # opens 默认 close*0.995 → 末阳线；close_pos=(11.1-10.3)/(11.2-10.3)≈0.89
        assert result["breakout_assessment"].startswith("放量突破")
        assert result["breakout_detail"]["at_60d_high"] is True

    def test_distribution_warning_on_weak_close(self):
        closes, vols = self._base()
        closes[-1] = 10.5
        result = _run(
            _mk_df(
                closes,
                vols[:-1] + [500.0],
                opens=None,
                highs=[max(a, b) * 1.002 for a, b in zip(closes, closes)][:-1] + [11.3],
                lows=[min(a, b) * 0.998 for a, b in zip(closes, closes)][:-1] + [10.2],
            )
        )
        # 收盘 10.5 虽高于横盘上沿，但位于当日区间 (10.2, 11.3) 下 28% → 滞涨
        assert "出货" in result["breakout_assessment"] or "滞涨" in result["breakout_assessment"]

    def test_no_signal_without_new_high(self):
        closes, vols = self._base()
        result = _run(_mk_df(closes, vols))
        assert result.get("breakout_assessment") is None


class TestPatternPosition:
    def test_high_position_prefix_on_bearish_pattern(self):
        # 下跌日放量（量价背离）且价格处于 60 日区间高位
        closes, vols = [], []
        px = 8.0
        for i in range(121):
            if i % 2 == 0:
                px *= 1.02
                vols.append(100.0)
            else:
                px *= 0.995
                vols.append(300.0)
            closes.append(px)
        result = _run(_mk_df(closes, vols))
        assert result["price_position_label"] == "高位"
        assert result["pattern"].startswith("高位·")

    def test_low_position_prefix(self):
        closes, vols = [], []
        px = 20.0
        for i in range(121):
            if i % 2 == 0:
                px *= 0.98
                vols.append(100.0)
            else:
                px *= 1.005
                vols.append(300.0)
            closes.append(px)
        result = _run(_mk_df(closes, vols))
        assert result["price_position_label"] == "低位"
        assert result["pattern"].startswith("低位·")


class TestEdgeCases:
    def test_insufficient_rows_returns_error(self):
        df = _mk_df([10.0, 10.1, 10.2, 10.1], [100.0] * 4)
        result = _run(df)
        assert "error" in result

    def test_backward_compatible_keys_preserved(self):
        closes = [10.0 + 0.01 * i for i in range(80)]
        vols = [100.0] * 80
        result = _run(_mk_df(closes, vols))
        for key in (
            "latest_volume",
            "avg_volume_5d",
            "avg_volume_20d",
            "volume_ratio_vs_5d",
            "avg_up_day_volume",
            "avg_down_day_volume",
            "volume_trend",
            "volume_price_corr",
            "pattern",
        ):
            assert key in result, key
