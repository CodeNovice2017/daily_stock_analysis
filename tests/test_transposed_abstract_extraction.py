# -*- coding: utf-8 -*-
"""[personal patch] akshare 转置表提取器：fundamental 数据不再静默丢失。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data_provider.fundamental_adapter import (
    _extract_latest_from_transposed_abstract,
    _pick_by_keywords,
)


def _build_transposed_df() -> pd.DataFrame:
    """模拟 akshare.stock_financial_abstract 的转置结构（指标为行、报告期为列）。"""
    return pd.DataFrame({
        "选项": ["常用指标", "常用指标", "常用指标"],
        "指标": ["归母净利润", "营业总收入", "经营现金流量净额"],
        "20260331": [1.486e9, 3.367e9, 1.348e10],
        "20251231": [3.696e9, 1.055e10, np.nan],  # 最新期部分缺失
    })


def _build_regular_df() -> pd.DataFrame:
    """常规结构（指标为列）——提取器应返回 None 让旧提取器接管。"""
    return pd.DataFrame({
        "股票代码": ["000783"],
        "归母净利润": [1.5e9],
        "营业总收入": [3.4e9],
    })


class TestExtractLatestFromTransposedAbstract:
    def test_transposed_shape_extracted(self):
        row = _extract_latest_from_transposed_abstract(_build_transposed_df())
        assert row is not None
        assert row["营业总收入"] == 3.367e9
        assert row["经营现金流量净额"] == 1.348e10

    def test_latest_period_column_used(self):
        row = _extract_latest_from_transposed_abstract(_build_transposed_df())
        # 20260331 是首个非空期 → 归母净利润取 Q1 值而非年报值
        assert row["归母净利润"] == 1.486e9

    def test_regular_shape_returns_none(self):
        # 常规表不含"指标"列 → None → 调用方回退到 _extract_latest_row
        assert _extract_latest_from_transposed_abstract(_build_regular_df()) is None

    def test_no_period_columns_returns_none(self):
        df = pd.DataFrame({"指标": ["x"], "值": [1]})
        assert _extract_latest_from_transposed_abstract(df) is None

    def test_all_periods_empty_returns_none(self):
        df = pd.DataFrame({"指标": ["x"], "20260331": [np.nan]})
        assert _extract_latest_from_transposed_abstract(df) is None

    def test_duplicate_indicator_names_dedup_first(self):
        df = pd.DataFrame({
            "选项": ["A组", "B组"],
            "指标": ["营业总收入", "营业总收入"],
            "20260331": [100.0, 200.0],
        })
        row = _extract_latest_from_transposed_abstract(df)
        assert row["营业总收入"] == 100.0

    def test_keyword_pick_on_extracted_row(self):
        # 端到端：提取后按指标名（行索引）挑值
        row = _extract_latest_from_transposed_abstract(_build_transposed_df())
        assert _pick_by_keywords(row, ["营业总收入", "营业收入"]) == 3.367e9
        assert _pick_by_keywords(row, ["经营现金流量净额", "经营现金流"]) == 1.348e10
