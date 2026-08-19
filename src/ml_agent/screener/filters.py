# -*- coding: utf-8 -*-
"""三层筛选器：硬性过滤 → 趋势筛选 → 综合评分。

数据全部来自 Tushare 5000 积分接口，纯规则化计算，不依赖 LLM。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ScreenResult:
    """单只股票的筛选+评分结果。"""

    code: str
    name: str
    industry: str = ""
    total_score: float = 0.0
    quality_score: float = 0.0  # 盈利质量 0-30
    growth_score: float = 0.0   # 成长性 0-25
    valuation_score: float = 0.0 # 估值安全 0-20
    trend_score: float = 0.0    # 趋势强度 0-15
    chip_score: float = 0.0     # 筹码与资金 0-10
    highlights: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "industry": self.industry,
            "total_score": round(self.total_score, 1),
            "quality_score": round(self.quality_score, 1),
            "growth_score": round(self.growth_score, 1),
            "valuation_score": round(self.valuation_score, 1),
            "trend_score": round(self.trend_score, 1),
            "chip_score": round(self.chip_score, 1),
            "highlights": self.highlights,
            "risks": self.risks,
            "details": self.details,
        }


# ──────────────────────────────────────────────
# 第一层：硬性过滤
# ──────────────────────────────────────────────

def filter_hard(
    stock_list: pd.DataFrame,
    daily_basic_map: Dict[str, Dict[str, float]],
    fina_map: Dict[str, Dict[str, Any]],
) -> List[str]:
    """硬性过滤，返回通过筛选的股票代码列表。

    Args:
        stock_list: ``stock_basic`` 返回的 DataFrame（含 code/name/industry）。
        daily_basic_map: ``{code: {pe, pb, total_mv, ...}}``。
        fina_map: ``{code: {roe, gross_margin, ...}}``。

    过滤条件：
        - 排除 ST/*ST
        - 排除上市 < 1 年
        - 排除 PE < 0 或 PE > 100
        - 排除 PB < 0
        - 最近 ROE > 5%
    """
    passed: List[str] = []
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    for _, row in stock_list.iterrows():
        code = row["code"]
        name = str(row.get("name", ""))

        # ST 排除
        if "ST" in name or "*ST" in name:
            continue

        # 上市时间（stock_basic 里没有 list_date 字段时跳过此检查）
        list_date = str(row.get("list_date", ""))
        if list_date and list_date < one_year_ago:
            # list_date 格式可能是 YYYYMMDD
            pass
        elif list_date and list_date >= one_year_ago:
            continue

        basic = daily_basic_map.get(code)
        if not basic:
            continue

        pe = basic.get("pe", 0)
        pb = basic.get("pb", 0)

        # PE 过滤
        if pe is not None and (pe <= 0 or pe > 100):
            continue

        # PB 过滤
        if pb is not None and pb <= 0:
            continue

        # ROE 过滤
        fina = fina_map.get(code)
        if not fina:
            continue
        roe = fina.get("roe", 0)
        if roe is None or roe < 5:
            continue

        passed.append(code)

    logger.info(f"[ML-Screen] 第一层硬性过滤: {len(stock_list)} → {len(passed)}")
    return passed


# ──────────────────────────────────────────────
# 第二层：趋势筛选（MA60/120）
# ──────────────────────────────────────────────

def filter_trend(
    codes: List[str],
    daily_map: Dict[str, pd.DataFrame],
) -> List[str]:
    """趋势筛选：MA20 > MA60、价格 > MA60、MA60 斜率向上。

    Args:
        codes: 第一层通过的股票代码。
        daily_map: ``{code: daily_df}``，每个 df 至少含 close 列，>= 120 行。

    要求日线数据 >= 120 个交易日，否则跳过。
    """
    passed: List[str] = []

    for code in codes:
        df = daily_map.get(code)
        if df is None or len(df) < 120:
            continue

        close = df["close"]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ma60_5d_ago = close.rolling(60).mean().iloc[-6]
        price = close.iloc[-1]

        if pd.isna(ma20) or pd.isna(ma60) or pd.isna(ma60_5d_ago):
            continue

        # MA20 > MA60（均线多头）
        if ma20 <= ma60:
            continue

        # 价格 > MA60（中期趋势向上）
        if price <= ma60:
            continue

        # MA60 斜率向上（5 日前 vs 现在）
        if ma60 <= ma60_5d_ago:
            continue

        passed.append(code)

    logger.info(f"[ML-Screen] 第二层趋势筛选: {len(codes)} → {len(passed)}")
    return passed
