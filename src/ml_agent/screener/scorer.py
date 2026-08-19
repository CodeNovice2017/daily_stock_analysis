# -*- coding: utf-8 -*-
"""综合评分器：对通过趋势筛选的股票进行五维度 100 分制评分。

维度权重：
    盈利质量 30 分（ROE/毛利率/净利率/ROE 趋势）
    成长性   25 分（营收增速/净利增速/增速加速度）
    估值安全 20 分（PE 分位/PB 分位/PEG）
    趋势强度 15 分（MA 多头程度/价格位置/成交量趋势）
    筹码资金 10 分（北向持股变化/股东增持/机构调研）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .filters import ScreenResult

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float = 0.0) -> float:
    """安全转 float，None/NaN/异常 → default。"""
    try:
        if val is None:
            return default
        f = float(val)
        if np.isnan(f) or np.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


# ──────────────────────────────────────────────
# 盈利质量评分 (30 分)
# ──────────────────────────────────────────────

def score_quality(fina: Dict[str, Any]) -> tuple[float, List[str], List[str]]:
    """盈利质量评分，返回 (score, highlights, risks)。"""
    score = 0.0
    highlights: List[str] = []
    risks: List[str] = []

    roe = _safe_float(fina.get("roe"))
    gross_margin = _safe_float(fina.get("grossprofit_margin"))
    net_margin = _safe_float(fina.get("netprofit_margin"))
    roe_trend = fina.get("roe_trend", "stable")

    # ROE（10 分）
    if roe >= 20:
        score += 10
        highlights.append(f"ROE {roe:.1f}%，盈利能力优秀")
    elif roe >= 15:
        score += 8
        highlights.append(f"ROE {roe:.1f}%，盈利能力良好")
    elif roe >= 10:
        score += 6
    elif roe >= 5:
        score += 3
    elif roe < 0:
        risks.append(f"ROE {roe:.1f}%，亏损")

    # 毛利率（8 分）
    if gross_margin >= 50:
        score += 8
        highlights.append(f"毛利率 {gross_margin:.1f}%，行业壁垒高")
    elif gross_margin >= 35:
        score += 6
    elif gross_margin >= 20:
        score += 4
    elif gross_margin < 15 and gross_margin > 0:
        risks.append(f"毛利率仅 {gross_margin:.1f}%，竞争激烈")

    # 净利率（6 分）
    if net_margin >= 20:
        score += 6
    elif net_margin >= 10:
        score += 4
    elif net_margin >= 5:
        score += 2
    elif net_margin < 0:
        risks.append(f"净利率 {net_margin:.1f}%，亏损")

    # ROE 趋势（6 分）
    if roe_trend == "up":
        score += 6
        highlights.append("ROE 逐季改善")
    elif roe_trend == "down":
        score += 0
        risks.append("ROE 环比下滑")
    else:
        score += 3

    return score, highlights, risks


# ──────────────────────────────────────────────
# 成长性评分 (25 分)
# ──────────────────────────────────────────────

def score_growth(fina: Dict[str, Any]) -> tuple[float, List[str], List[str]]:
    """成长性评分。"""
    score = 0.0
    highlights: List[str] = []
    risks: List[str] = []

    rev_yoy = _safe_float(fina.get("or_yoy"))   # 营收同比增速
    net_yoy = _safe_float(fina.get("netprofit_yoy"))  # 净利同比增速
    q_net_yoy = _safe_float(fina.get("q_profit_yoy"))  # 单季净利同比

    # 营收增速（10 分）
    if rev_yoy >= 30:
        score += 10
        highlights.append(f"营收增速 {rev_yoy:.1f}%，高成长")
    elif rev_yoy >= 15:
        score += 8
        highlights.append(f"营收增速 {rev_yoy:.1f}%，稳健成长")
    elif rev_yoy >= 5:
        score += 5
    elif rev_yoy >= 0:
        score += 2
    else:
        risks.append(f"营收增速 {rev_yoy:.1f}%，负增长")

    # 净利增速（10 分）
    if net_yoy >= 50:
        score += 10
        highlights.append(f"净利增速 {net_yoy:.1f}%，业绩爆发")
    elif net_yoy >= 30:
        score += 8
        highlights.append(f"净利增速 {net_yoy:.1f}%，高速增长")
    elif net_yoy >= 15:
        score += 6
    elif net_yoy >= 0:
        score += 3
    else:
        risks.append(f"净利增速 {net_yoy:.1f}%，负增长")

    # 增速加速度（5 分）：单季同比 vs 累计同比
    if q_net_yoy > 0 and net_yoy > 0 and q_net_yoy > net_yoy:
        score += 5
        highlights.append("业绩增速环比加速")
    elif q_net_yoy > 0:
        score += 2
    elif q_net_yoy < 0 and net_yoy < 0:
        risks.append("单季业绩同比转负")

    return score, highlights, risks


# ──────────────────────────────────────────────
# 估值安全评分 (20 分)
# ──────────────────────────────────────────────

def score_valuation(
    pe: float,
    pb: float,
    pe_percentile: Optional[float] = None,
    pb_percentile: Optional[float] = None,
) -> tuple[float, List[str], List[str]]:
    """估值安全评分。

    Args:
        pe: 当前 PE。
        pb: 当前 PB。
        pe_percentile: PE 近 3 年分位 (0-1)，None 表示无法计算。
        pb_percentile: PB 近 3 年分位 (0-1)。
    """
    score = 0.0
    highlights: List[str] = []
    risks: List[str] = []

    # PE 分位（8 分）
    if pe_percentile is not None:
        if pe_percentile < 0.2:
            score += 8
            highlights.append(f"PE 处近 3 年 {pe_percentile*100:.0f}% 分位，极度低估")
        elif pe_percentile < 0.4:
            score += 6
            highlights.append(f"PE 处近 3 年 {pe_percentile*100:.0f}% 分位，偏低")
        elif pe_percentile < 0.6:
            score += 4
        elif pe_percentile < 0.8:
            score += 2
        else:
            risks.append(f"PE 处近 3 年 {pe_percentile*100:.0f}% 分位，偏高")
    else:
        # 没有分位数据时用绝对值
        if 0 < pe <= 15:
            score += 8
        elif 15 < pe <= 25:
            score += 6
        elif 25 < pe <= 40:
            score += 3

    # PB 分位（6 分）
    if pb_percentile is not None:
        if pb_percentile < 0.2:
            score += 6
            highlights.append(f"PB 处近 3 年 {pb_percentile*100:.0f}% 分位，低估")
        elif pb_percentile < 0.5:
            score += 4
        elif pb_percentile < 0.8:
            score += 2
        else:
            risks.append(f"PB 处近 3 年 {pb_percentile*100:.0f}% 分位，偏高")
    else:
        if 0 < pb <= 1.5:
            score += 6
            highlights.append(f"PB {pb:.1f}，破净边缘")
        elif pb <= 2.5:
            score += 4
        elif pb <= 4:
            score += 2

    # PEG（6 分）—— 简化版：PE / 净利增速
    # 由调用方传入 peg，这里不单独计算
    peg = pe_percentile  # placeholder，外部应直接传 peg
    # PEG 在 score_all 里单独计算

    return score, highlights, risks


# ──────────────────────────────────────────────
# 趋势强度评分 (15 分)
# ──────────────────────────────────────────────

def score_trend(daily_df: pd.DataFrame) -> tuple[float, List[str], List[str], Dict[str, Any]]:
    """趋势强度评分，基于 MA20/60/120 和成交量。

    Returns:
        (score, highlights, risks, detail_dict)
    """
    score = 0.0
    highlights: List[str] = []
    risks: List[str] = []
    detail: Dict[str, Any] = {}

    if len(daily_df) < 120:
        return score, highlights, risks, detail

    close = daily_df["close"]
    volume = daily_df["volume"] if "volume" in daily_df else pd.Series(dtype=float)

    price = close.iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ma120 = close.rolling(120).mean().iloc[-1]

    detail.update({"price": price, "ma20": ma20, "ma60": ma60, "ma120": ma120})

    # MA 多头程度（8 分）
    if not any(pd.isna(x) for x in [ma20, ma60, ma120]):
        if price > ma20 > ma60 > ma120:
            score += 8
            highlights.append("MA20>60>120 完整多头排列")
            detail["ma_alignment"] = "full_bull"
        elif ma20 > ma60:
            score += 5
            detail["ma_alignment"] = "partial_bull"
        else:
            detail["ma_alignment"] = "mixed"

    # 价格位置（4 分）：价格相对 MA60 的位置
    if not pd.isna(ma60) and ma60 > 0:
        bias_ma60 = (price - ma60) / ma60
        detail["bias_ma60"] = f"{bias_ma60*100:.1f}%"
        if 0 < bias_ma60 < 0.05:
            score += 4  # 回踩 MA60 附近，理想买点
            highlights.append("价格回踩 MA60 附近，趋势买点")
        elif 0.05 <= bias_ma60 < 0.15:
            score += 3
        elif bias_ma60 >= 0.15:
            score += 1
            risks.append(f"乖离 MA60 达 {bias_ma60*100:.1f}%，短期偏高")

    # 成交量趋势（3 分）：近 5 日均量 vs 20 日均量
    if len(volume) >= 20:
        vol_ma5 = volume.rolling(5).mean().iloc[-1]
        vol_ma20 = volume.rolling(20).mean().iloc[-1]
        if not pd.isna(vol_ma5) and not pd.isna(vol_ma20) and vol_ma20 > 0:
            vol_ratio = vol_ma5 / vol_ma20
            detail["vol_ratio"] = round(vol_ratio, 2)
            if 0.7 <= vol_ratio <= 1.0:
                score += 3  # 缩量整理，趋势健康
            elif vol_ratio < 0.7:
                score += 2  # 极度缩量，可能变盘
            elif vol_ratio <= 1.5:
                score += 1  # 温和放量

    return score, highlights, risks, detail


# ──────────────────────────────────────────────
# 筹码与资金评分 (10 分)
# ──────────────────────────────────────────────

def score_chip(
    holder_trade: Optional[Dict] = None,
    hk_hold_change: Optional[float] = None,
    surv_flag: bool = False,
) -> tuple[float, List[str], List[str]]:
    """筹码与资金评分。

    Args:
        holder_trade: 股东增减持数据，含 net_buy 字段（万元）。
        hk_hold_change: 北向持股比例变化（百分点），正=增持。
        surv_flag: 是否有机构调研。
    """
    score = 0.0
    highlights: List[str] = []
    risks: List[str] = []

    # 北向持股变化（4 分）
    if hk_hold_change is not None:
        if hk_hold_change > 0.5:
            score += 4
            highlights.append(f"北向持股增加 {hk_hold_change:.2f}%，外资看好")
        elif hk_hold_change > 0:
            score += 2
        elif hk_hold_change < -0.5:
            risks.append(f"北向持股减少 {abs(hk_hold_change):.2f}%，外资撤退")

    # 股东增减持（3 分）
    if holder_trade:
        net_buy = _safe_float(holder_trade.get("net_buy"))
        if net_buy > 5000:
            score += 3
            highlights.append(f"重要股东净增持 {net_buy/1e4:.1f} 亿元")
        elif net_buy > 0:
            score += 1
        elif net_buy < -5000:
            risks.append(f"重要股东净减持 {abs(net_buy)/1e4:.1f} 亿元")

    # 机构调研（3 分）
    if surv_flag:
        score += 3
        highlights.append("近期有机构调研")

    return score, highlights, risks


# ──────────────────────────────────────────────
# 估值分位计算
# ──────────────────────────────────────────────

def compute_pe_pb_percentile(
    daily_basic_df: pd.DataFrame,
) -> tuple[Optional[float], Optional[float]]:
    """从 daily_basic 历史数据计算 PE/PB 近 3 年分位。

    Args:
        daily_basic_df: 含 pe, pb 列的 DataFrame，按日期排序。

    Returns:
        (pe_percentile, pb_percentile)，0-1 范围，None 表示数据不足。
    """
    if daily_basic_df is None or len(daily_basic_df) < 60:
        return None, None

    pe_series = daily_basic_df["pe"].dropna()
    pb_series = daily_basic_df["pb"].dropna()
    if pe_series.empty or pb_series.empty:
        return None, None

    pe_now = pe_series.iloc[-1]
    pb_now = pb_series.iloc[-1]

    pe_pct = (pe_series < pe_now).sum() / len(pe_series) if pe_now > 0 else None
    pb_pct = (pb_series < pb_now).sum() / len(pb_series) if pb_now > 0 else None

    return pe_pct, pb_pct


# ──────────────────────────────────────────────
# 综合评分入口
# ──────────────────────────────────────────────

def score_stock(
    code: str,
    name: str,
    industry: str,
    fina: Dict[str, Any],
    daily_df: pd.DataFrame,
    daily_basic_now: Dict[str, float],
    daily_basic_hist: Optional[pd.DataFrame] = None,
    holder_trade: Optional[Dict] = None,
    hk_hold_change: Optional[float] = None,
    surv_flag: bool = False,
) -> ScreenResult:
    """对单只股票执行五维度综合评分。

    这是选股引擎第三层的核心函数。所有子评分函数的结果汇总到 ScreenResult。
    """
    all_highlights: List[str] = []
    all_risks: List[str] = []

    # 1. 盈利质量 (30 分)
    q_score, q_hl, q_rk = score_quality(fina)
    all_highlights.extend(q_hl)
    all_risks.extend(q_rk)

    # 2. 成长性 (25 分)
    g_score, g_hl, g_rk = score_growth(fina)
    all_highlights.extend(g_hl)
    all_risks.extend(g_rk)

    # 3. 估值安全 (20 分)
    pe = _safe_float(daily_basic_now.get("pe"))
    pb = _safe_float(daily_basic_now.get("pb"))
    pe_pct, pb_pct = compute_pe_pb_percentile(daily_basic_hist)
    v_score, v_hl, v_rk = score_valuation(pe, pb, pe_pct, pb_pct)
    all_highlights.extend(v_hl)
    all_risks.extend(v_rk)

    # 4. 趋势强度 (15 分)
    t_score, t_hl, t_rk, trend_detail = score_trend(daily_df)
    all_highlights.extend(t_hl)
    all_risks.extend(t_rk)

    # 5. 筹码资金 (10 分)
    c_score, c_hl, c_rk = score_chip(holder_trade, hk_hold_change, surv_flag)
    all_highlights.extend(c_hl)
    all_risks.extend(c_rk)

    total = q_score + g_score + v_score + t_score + c_score

    return ScreenResult(
        code=code,
        name=name,
        industry=industry,
        total_score=total,
        quality_score=q_score,
        growth_score=g_score,
        valuation_score=v_score,
        trend_score=t_score,
        chip_score=c_score,
        highlights=all_highlights[:5],  # 取前 5 条
        risks=all_risks[:3],
        details={
            **trend_detail,
            "pe": pe,
            "pb": pb,
            "pe_percentile": pe_pct,
            "pb_percentile": pb_pct,
        },
    )
