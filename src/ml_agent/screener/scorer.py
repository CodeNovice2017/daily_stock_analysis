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

def score_quality(
    fina: Dict[str, Any],
    cash_ratio: Optional[float] = None,
) -> tuple[float, List[str], List[str]]:
    """盈利质量评分，返回 (score, highlights, risks)。

    [personal patch] P2：加入现金流实现率子因子（经营现金流/净利润，
    Sloan 1996 应计异象的镜像）——利润是否有现金流背书，与常见风格
    因子相关性低（A股实证见 docs/design-medium-long-term-module.md）。
    权重 30 = ROE 9 + 毛利率 7 + 净利率 5 + ROE趋势 4 + 现金流实现率 5。
    """
    score = 0.0
    highlights: List[str] = []
    risks: List[str] = []

    roe = _safe_float(fina.get("roe"))
    gross_margin = _safe_float(fina.get("grossprofit_margin"))
    net_margin = _safe_float(fina.get("netprofit_margin"))
    roe_trend = fina.get("roe_trend", "stable")

    # ROE（9 分）
    if roe >= 20:
        score += 9
        highlights.append(f"ROE {roe:.1f}%，盈利能力优秀")
    elif roe >= 15:
        score += 7
        highlights.append(f"ROE {roe:.1f}%，盈利能力良好")
    elif roe >= 10:
        score += 5
    elif roe >= 5:
        score += 3
    elif roe < 0:
        risks.append(f"ROE {roe:.1f}%，亏损")

    # 毛利率（7 分）
    if gross_margin >= 50:
        score += 7
        highlights.append(f"毛利率 {gross_margin:.1f}%，行业壁垒高")
    elif gross_margin >= 35:
        score += 5
    elif gross_margin >= 20:
        score += 3
    elif gross_margin < 15 and gross_margin > 0:
        risks.append(f"毛利率仅 {gross_margin:.1f}%，竞争激烈")

    # 净利率（5 分）
    if net_margin >= 20:
        score += 5
    elif net_margin >= 10:
        score += 3
    elif net_margin >= 5:
        score += 2
    elif net_margin < 0:
        risks.append(f"净利率 {net_margin:.1f}%，亏损")

    # ROE 趋势（4 分）
    if roe_trend == "up":
        score += 4
        highlights.append("ROE 逐季改善")
    elif roe_trend == "down":
        score += 0
        risks.append("ROE 环比下滑")
    else:
        score += 2

    # 现金流实现率（5 分）：经营现金流 / 净利润
    if cash_ratio is not None:
        if cash_ratio >= 1.3:
            score += 5
            highlights.append(f"现金流实现率 {cash_ratio:.2f}，利润有现金背书")
        elif cash_ratio >= 1.0:
            score += 4
        elif cash_ratio >= 0.7:
            score += 2
        elif cash_ratio >= 0.4:
            score += 1
            risks.append(f"现金流实现率仅 {cash_ratio:.2f}，部分利润未转化为现金")
        else:
            risks.append(f"现金流实现率 {cash_ratio:.2f}，利润质量差（应计占比高）")

    return score, highlights, risks


# ──────────────────────────────────────────────
# 成长性评分 (25 分)
# ──────────────────────────────────────────────

def compute_sue(single_quarters: Optional[List[float]]) -> Optional[float]:
    """时序 SUE（标准未预期盈余，不带漂移项）。

    [personal patch] P2：A股实证（东方证券《业绩超预期类因子》等）显示
    行业市值中性化后的 SUE RankIC 约 4%，且"不带漂移项的时序 SUE"表现
    最佳——单股层面即可计算，无需横截面回归基建。

    Args:
        single_quarters: 单季净利润序列（按时间升序，最新在末尾），
            至少需要 5 期（均值 4 期 + 当期），9 期可用完整 8 期波动率。

    Returns:
        SUE 值；数据不足或波动率为 0 时返回 None。
    """
    if not single_quarters or len(single_quarters) < 5:
        return None
    try:
        qs = [float(x) for x in single_quarters if x is not None]
    except (TypeError, ValueError):
        return None
    if len(qs) < 5 or any(q is None for q in qs):
        return None
    latest = qs[-1]
    prev4 = qs[-5:-1]
    hist = qs[-9:-1] if len(qs) >= 9 else qs[:-1]
    mean_prev = sum(prev4) / len(prev4)
    var = sum((x - mean_prev) ** 2 for x in hist) / max(len(hist) - 1, 1)
    std = var ** 0.5
    if std <= 0:
        return None
    return (latest - mean_prev) / std


def score_growth(
    fina: Dict[str, Any],
    sue: Optional[float] = None,
) -> tuple[float, List[str], List[str]]:
    """成长性评分。

    [personal patch] P2：加入 SUE（盈余惊喜）主因子。PEAD 在 A 股持续
    3-6 个月，是选股窗口内最强的可量化学术因子之一。
    权重 28 = 营收 7 + 净利 7 + 加速 4 + SUE 10。
    """
    score = 0.0
    highlights: List[str] = []
    risks: List[str] = []

    rev_yoy = _safe_float(fina.get("or_yoy"))   # 营收同比增速
    net_yoy = _safe_float(fina.get("netprofit_yoy"))  # 净利同比增速
    q_net_yoy = _safe_float(fina.get("q_profit_yoy"))  # 单季净利同比

    # 营收增速（7 分）
    if rev_yoy >= 30:
        score += 7
        highlights.append(f"营收增速 {rev_yoy:.1f}%，高成长")
    elif rev_yoy >= 15:
        score += 5
        highlights.append(f"营收增速 {rev_yoy:.1f}%，稳健成长")
    elif rev_yoy >= 5:
        score += 3
    elif rev_yoy >= 0:
        score += 1
    else:
        risks.append(f"营收增速 {rev_yoy:.1f}%，负增长")

    # 净利增速（7 分）
    if net_yoy >= 50:
        score += 7
        highlights.append(f"净利增速 {net_yoy:.1f}%，业绩爆发")
    elif net_yoy >= 30:
        score += 5
        highlights.append(f"净利增速 {net_yoy:.1f}%，高速增长")
    elif net_yoy >= 15:
        score += 4
    elif net_yoy >= 0:
        score += 2
    else:
        risks.append(f"净利增速 {net_yoy:.1f}%，负增长")

    # 增速加速度（4 分）：单季同比 vs 累计同比
    if q_net_yoy > 0 and net_yoy > 0 and q_net_yoy > net_yoy:
        score += 4
        highlights.append("业绩增速环比加速")
    elif q_net_yoy > 0:
        score += 2
    elif q_net_yoy < 0 and net_yoy < 0:
        risks.append("单季业绩同比转负")

    # SUE 盈余惊喜（10 分）
    if sue is not None:
        if sue >= 1.5:
            score += 10
            highlights.append(f"SUE {sue:.2f}，盈余大幅超预期（PEAD 窗口）")
        elif sue >= 0.8:
            score += 7
            highlights.append(f"SUE {sue:.2f}，盈余超预期")
        elif sue >= 0.3:
            score += 5
        elif sue >= -0.3:
            score += 3
        elif sue >= -0.8:
            score += 1
        else:
            risks.append(f"SUE {sue:.2f}，盈余显著低于预期")

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

    [personal patch] P2：估值为 2 周-3 个月窗口的弱因子（A股实证），
    权重 20 → 12，腾出的 8 分给成长（SUE）与趋势（残差动量）。
    权重 12 = PE 7 + PB 5。

    Args:
        pe: 当前 PE。
        pb: 当前 PB。
        pe_percentile: PE 近 3 年分位 (0-1)，None 表示无法计算。
        pb_percentile: PB 近 3 年分位 (0-1)。
    """
    score = 0.0
    highlights: List[str] = []
    risks: List[str] = []

    # PE 分位（7 分）
    if pe_percentile is not None:
        if pe_percentile < 0.2:
            score += 7
            highlights.append(f"PE 处近 3 年 {pe_percentile*100:.0f}% 分位，极度低估")
        elif pe_percentile < 0.4:
            score += 5
            highlights.append(f"PE 处近 3 年 {pe_percentile*100:.0f}% 分位，偏低")
        elif pe_percentile < 0.6:
            score += 3
        elif pe_percentile < 0.8:
            score += 1
        else:
            risks.append(f"PE 处近 3 年 {pe_percentile*100:.0f}% 分位，偏高")
    else:
        # 没有分位数据时用绝对值
        if 0 < pe <= 15:
            score += 7
        elif 15 < pe <= 25:
            score += 5
        elif 25 < pe <= 40:
            score += 2

    # PB 分位（5 分）
    if pb_percentile is not None:
        if pb_percentile < 0.2:
            score += 5
            highlights.append(f"PB 处近 3 年 {pb_percentile*100:.0f}% 分位，低估")
        elif pb_percentile < 0.5:
            score += 3
        elif pb_percentile < 0.8:
            score += 1
        else:
            risks.append(f"PB 处近 3 年 {pb_percentile*100:.0f}% 分位，偏高")
    else:
        if 0 < pb <= 1.5:
            score += 5
            highlights.append(f"PB {pb:.1f}，破净边缘")
        elif pb <= 2.5:
            score += 3
        elif pb <= 4:
            score += 1

    return score, highlights, risks


# ──────────────────────────────────────────────
# 趋势强度评分 (15 分)
# ──────────────────────────────────────────────

def compute_residual_momentum(
    stock_close: "pd.Series",
    index_close: "pd.Series",
    window: int = 120,
) -> Optional[float]:
    """残差动量（Blitz 标准化）。

    [personal patch] P2：A股实证显示价格动量 IC 为负（反转市场），
    剥离系统性风险后的残差动量方向转正（Lin 2020；BigQuant 因子研究）。
    计算个股日收益对指数日收益 OLS 回归的残差，取残差的年化 Sharpe。

    Args:
        stock_close / index_close: 按 date 对齐前的收盘价序列（带日期索引）。
        window: 回归与度量窗口（交易日，默认 120）。

    Returns:
        残差 Sharpe；数据不足/方差退化时 None。
    """
    try:
        joined = pd.concat(
            [stock_close.rename("s"), index_close.rename("m")], axis=1, join="inner"
        ).dropna()
        if len(joined) < 60:
            return None
        joined = joined.tail(window)
        ret_s = joined["s"].pct_change().dropna()
        ret_m = joined["m"].pct_change().dropna()
        n = min(len(ret_s), len(ret_m))
        if n < 60:
            return None
        ret_s, ret_m = ret_s.tail(n), ret_m.tail(n)
        var_m = float(ret_m.var())
        if var_m > 0:
            cov = float((ret_s * ret_m).mean() - ret_s.mean() * ret_m.mean()) * n / (n - 1)
            beta = cov / var_m
        else:
            # 市场完全横盘时 beta 退化为 0：个股全部收益即残差
            beta = 0.0
        resid = ret_s - beta * ret_m
        ann_vol = float(resid.std()) * (252 ** 0.5)
        if ann_vol <= 0:
            return None
        ann_ret = float(resid.mean()) * 252
        return ann_ret / ann_vol
    except Exception:
        return None


def score_trend(
    daily_df: pd.DataFrame,
    index_df: Optional[pd.DataFrame] = None,
) -> tuple[float, List[str], List[str], Dict[str, Any]]:
    """趋势强度评分，基于 MA20/60/120、成交量与残差动量。

    [personal patch] P2：加入残差动量主因子（A股实证方向修正）。
    权重 20 = MA 6 + 乖离 3 + 量能 2 + 残差动量 9。
    index_df 缺失时残差动量计 0 分并记录原因（保守处理）。

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

    # MA 多头程度（6 分）
    if not any(pd.isna(x) for x in [ma20, ma60, ma120]):
        if price > ma20 > ma60 > ma120:
            score += 6
            highlights.append("MA20>60>120 完整多头排列")
            detail["ma_alignment"] = "full_bull"
        elif ma20 > ma60:
            score += 4
            detail["ma_alignment"] = "partial_bull"
        else:
            detail["ma_alignment"] = "mixed"

    # 价格位置（3 分）：价格相对 MA60 的位置
    if not pd.isna(ma60) and ma60 > 0:
        bias_ma60 = (price - ma60) / ma60
        detail["bias_ma60"] = f"{bias_ma60*100:.1f}%"
        if 0 < bias_ma60 < 0.05:
            score += 3  # 回踩 MA60 附近，理想买点
            highlights.append("价格回踩 MA60 附近，趋势买点")
        elif 0.05 <= bias_ma60 < 0.15:
            score += 2
        elif bias_ma60 >= 0.15:
            score += 1
            risks.append(f"乖离 MA60 达 {bias_ma60*100:.1f}%，短期偏高")

    # 成交量趋势（2 分）：近 5 日均量 vs 20 日均量
    if len(volume) >= 20:
        vol_ma5 = volume.rolling(5).mean().iloc[-1]
        vol_ma20 = volume.rolling(20).mean().iloc[-1]
        if not pd.isna(vol_ma5) and not pd.isna(vol_ma20) and vol_ma20 > 0:
            vol_ratio = vol_ma5 / vol_ma20
            detail["vol_ratio"] = round(vol_ratio, 2)
            if 0.7 <= vol_ratio <= 1.0:
                score += 2  # 缩量整理，趋势健康
            elif vol_ratio < 0.7:
                score += 1  # 极度缩量，可能变盘
            elif vol_ratio <= 1.5:
                score += 1  # 温和放量

    # 残差动量（9 分）
    resid_mom = None
    if index_df is not None and not index_df.empty and "close" in index_df and "date" in daily_df.columns:
        try:
            s = pd.Series(close.values, index=pd.to_datetime(daily_df["date"]))
            m = pd.Series(
                index_df["close"].values, index=pd.to_datetime(index_df["date"])
            )
            resid_mom = compute_residual_momentum(s, m)
        except Exception:
            resid_mom = None
    if resid_mom is not None:
        detail["residual_momentum"] = round(resid_mom, 2)
        if resid_mom >= 2.0:
            score += 9
            highlights.append(f"残差动量 {resid_mom:.1f}，独立于大盘的强势")
        elif resid_mom >= 1.0:
            score += 7
            highlights.append(f"残差动量 {resid_mom:.1f}，超额趋势明确")
        elif resid_mom >= 0.3:
            score += 5
        elif resid_mom >= -0.3:
            score += 3
        elif resid_mom >= -1.0:
            score += 1
        else:
            risks.append(f"残差动量 {resid_mom:.1f}，独立走势显著走弱")
    else:
        detail["residual_momentum"] = None

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
    sue: Optional[float] = None,
    cash_ratio: Optional[float] = None,
    index_df: Optional[pd.DataFrame] = None,
) -> ScreenResult:
    """对单只股票执行五维度综合评分。

    这是选股引擎第三层的核心函数。所有子评分函数的结果汇总到 ScreenResult。

    [personal patch] P2 因子修订（2026-08-20，实证依据见
    docs/design-medium-long-term-module.md）：
        质量 30（含现金流实现率 5）+ 成长 28（含 SUE 10）
        + 估值 12（弱因子降权）+ 趋势 20（含残差动量 9）+ 筹码 10 = 100
    """
    all_highlights: List[str] = []
    all_risks: List[str] = []

    # 1. 盈利质量 (30 分)
    q_score, q_hl, q_rk = score_quality(fina, cash_ratio=cash_ratio)
    all_highlights.extend(q_hl)
    all_risks.extend(q_rk)

    # 2. 成长性 (28 分)
    g_score, g_hl, g_rk = score_growth(fina, sue=sue)
    all_highlights.extend(g_hl)
    all_risks.extend(g_rk)

    # 3. 估值安全 (12 分)
    pe = _safe_float(daily_basic_now.get("pe"))
    pb = _safe_float(daily_basic_now.get("pb"))
    pe_pct, pb_pct = compute_pe_pb_percentile(daily_basic_hist)
    v_score, v_hl, v_rk = score_valuation(pe, pb, pe_pct, pb_pct)
    all_highlights.extend(v_hl)
    all_risks.extend(v_rk)

    # 4. 趋势强度 (20 分)
    t_score, t_hl, t_rk, trend_detail = score_trend(daily_df, index_df=index_df)
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
