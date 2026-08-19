# -*- coding: utf-8 -*-
"""中长线个股分析的三个分析师 Agent + 多空辩论 + 投资经理。

流程：
    数据准备 → 基本面 Agent / 趋势 Agent / 风控 Agent（并行）
    → 多头研究员 + 空头研究员（辩论）
    → 投资经理（最终决策）

每个角色都有独立的 system prompt，确保分析视角不混淆。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..llm_client import chat

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════
# System Prompts
# ════════════════════════════════════════════════

FUNDAMENTAL_PROMPT = """你是一位专注于中长线投资的基本面分析师。你的任务是深度分析公司财务数据，产出专业的基本面报告。

分析框架（必须覆盖）：
1. **盈利能力**：ROE 绝对值 + 连续 4 季度趋势（上升/走平/下降），毛利率和净利率的行业竞争力
2. **成长性**：营收增速、净利润增速，以及增速是否在加速（季度环比）
3. **财务健康**：资产负债率、流动比率/速动比率、经营现金流 vs 净利润匹配度
4. **盈利质量**：自由现金流是否为正、商誉占净资产比例、应收账款周转
5. **分红回报**：股息率、分红率稳定性

输出要求：
- 评分（0-100），0 分极差，100 分极优
- 3 个核心亮点
- 3 个核心风险
- 200 字以内总结

用 Markdown 格式输出。数据必须引用给定的财务数据，不得编造。"""


TREND_PROMPT = """你是一位专注于中长线趋势分析的技术分析师。你的任务是基于 MA20/MA60/MA120 均线体系和估值分位，判断当前趋势阶段。

分析框架（必须覆盖）：
1. **大趋势方向**：MA60 和 MA120 的方向（上升/走平/下降），这是中长期趋势的基石
2. **均线排列**：MA20 vs MA60 vs MA120 的相对位置（完整多头/部分多头/空头排列/缠绕）
3. **价格位置**：当前价格相对 MA60 的乖离率，是否在理想买入区间（回踩 MA60 附近）
4. **估值区间**：PE/PB 近 3 年历史分位（<30% 低估，30-70% 合理，>70% 高估）
5. **趋势阶段判断**：底部构筑 / 上升趋势 / 顶部区域 / 下降趋势

输出要求：
- 趋势评分（0-100）
- 趋势阶段：底部/上升/顶部/下降
- 理想买入区间（给出价格范围）
- 支撑位和阻力位
- 200 字以内总结

用 Markdown 格式输出。"""


RISK_PROMPT = """你是一位严谨的风险控制分析师。你的任务是做五维风险排查，识别潜在的"黑天鹅"和已知风险。

排查清单（每一项都必须检查）：
1. **解禁风险**：未来 3 个月限售股解禁市值占流通市值比例，>10% 为高风险
2. **减持风险**：重要股东近 90 天净增减持方向
3. **财报风险**：业绩预告是否预减、审计意见是否非标
4. **商誉风险**：商誉占净资产比例，>30% 存在减值风险
5. **行业风险**：所处行业是否处于下行周期，是否有政策打压

输出要求：
- 风险等级：低/中/高
- 每个维度的具体发现（如果数据缺失，标注"数据不足"而非编造）
- 是否存在"一票否决"项（非标审计/业绩断崖/重大违规）
- 150 字以内总结

用 Markdown 格式输出。"""


BULL_PROMPT = """你是多头研究员，你的任务是构建最强有力的看多论据。你将获得基本面、趋势和风控三个分析师的报告，以及财务数据。

你必须：
- 从基本面报告中找到增长和估值优势的证据
- 从趋势报告中找到趋势向上的证据
- 提出催化剂（业绩催化、行业政策、公司事件等）
- 正面回应空头可能的质疑

输出 300 字以内的多头论据，要有逻辑和数据支撑，不是空洞的看多口号。"""


BEAR_PROMPT = """你是空头研究员，你的任务是构建最强有力的看空论据。你将获得基本面、趋势和风控三个分析师的报告，以及财务数据。

你必须：
- 从基本面报告中找到盈利质量隐忧和财务风险
- 从趋势报告中找到趋势走弱的信号
- 指出估值泡沫或下行风险
- 提出潜在的利空催化（行业周期、解禁、减持等）

输出 300 字以内的空头论据，要有逻辑和数据支撑，不是空洞的看空口号。"""


MANAGER_PROMPT = """你是投资经理，需要综合多空辩论结果，输出最终投资决策。

你将收到：
- 基本面分析师报告
- 趋势分析师报告
- 风控分析师报告
- 多头研究员论据
- 空头研究员论据

决策要求：
1. 评级：Buy / Overweight / Hold / Underweight / Sell（五级）
2. 信心度：高/中/低
3. 投资周期：1-3 个月 / 3-6 个月 / 6-12 个月
4. 操作计划：入场区间、加仓区间、止损位、目标位1、目标位2
5. 仓位建议（占总资金比例）

输出 JSON 格式：
```json
{
  "ticker": "股票代码",
  "name": "股票名称",
  "rating": "评级",
  "confidence": "信心度",
  "timeframe": "投资周期",
  "fundamental_score": 0,
  "trend_score": 0,
  "risk_level": "风险等级",
  "bull_case": "多头核心论据（100字）",
  "bear_case": "空头核心论据（100字）",
  "verdict": "综合判断（200字）",
  "action_plan": {
    "entry_zone": "入场区间",
    "add_zone": "加仓区间",
    "stop_loss": "止损位",
    "target_1": "目标位1",
    "target_2": "目标位2",
    "position_size": "仓位建议"
  }
}
```

只输出 JSON，不要其他文字。"""


# ════════════════════════════════════════════════
# Agent 函数
# ════════════════════════════════════════════════

def run_fundamental_agent(data: Dict[str, Any]) -> str:
    """基本面分析 Agent。

    Args:
        data: 含 fina（财务指标）、forecast（业绩预告）、financials（三表）、code/name 等。
    """
    fina = data.get("fina", {})
    forecast = data.get("forecast")
    financials = data.get("financials")
    name = data.get("name", "")
    code = data.get("code", "")

    # 构建用户提示词
    user_parts = [f"# {name}({code}) 财务数据\n"]

    # 财务指标
    user_parts.append("## 最近 4 个季度财务指标")
    for q in fina.get("trend", []):
        user_parts.append(
            f"- {q['period']}: ROE={q.get('roe',0):.2f}% "
            f"毛利率={q.get('grossprofit_margin',0):.1f}% "
            f"净利率={q.get('netprofit_margin',0):.1f}% "
            f"营收增速={q.get('or_yoy',0):.1f}% "
            f"净利增速={q.get('netprofit_yoy',0):.1f}% "
            f"资产负债率={q.get('debt_to_assets',0):.1f}%"
        )

    # 最新季度速动比率等
    latest = fina.get("latest", {})
    if latest:
        user_parts.append(f"\n## 最新季度扩展指标")
        user_parts.append(f"- ROA: {latest.get('roa',0):.2f}%")
        user_parts.append(f"- 速动比率: {latest.get('quick_ratio',0):.2f}")
        user_parts.append(f"- EPS: {latest.get('eps',0):.2f}")
        user_parts.append(f"- BPS: {latest.get('bps',0):.2f}")

    # 三大报表关键数据
    if financials:
        bs = financials.get("balance_sheet", {})
        if bs:
            user_parts.append(f"\n## 资产负债表关键项")
            user_parts.append(f"- 商誉: {bs.get('goodwill',0)/1e8:.2f} 亿元（占净资产 {bs.get('goodwill_to_equity',0):.1f}%）")
            user_parts.append(f"- 应收账款: {bs.get('accounts_receivable',0)/1e8:.2f} 亿元")
            user_parts.append(f"- 货币资金: {bs.get('cash',0)/1e8:.2f} 亿元")
            user_parts.append(f"- 总资产: {bs.get('total_assets',0)/1e8:.0f} 亿元")
            user_parts.append(f"- 总负债: {bs.get('total_liab',0)/1e8:.0f} 亿元")

        cf_list = financials.get("cashflow", [])
        if cf_list:
            user_parts.append(f"\n## 现金流量表（近{len(cf_list)}季度）")
            for cf in cf_list[:4]:
                ocf = cf.get("operating_cf", 0)
                fcf = cf.get("free_cashflow", 0)
                user_parts.append(f"- {cf['period']}: 经营CF={ocf/1e8:.1f}亿 自由CF={fcf/1e8 if fcf else 0:.1f}亿")

        inc_list = financials.get("income", [])
        if inc_list:
            user_parts.append(f"\n## 利润表绝对值（近{len(inc_list)}季度）")
            for inc in inc_list[:4]:
                user_parts.append(f"- {inc['period']}: 营收={inc.get('revenue',0)/1e8:.1f}亿 净利={inc.get('n_income',0)/1e8:.1f}亿")

    # 业绩预告
    if forecast:
        user_parts.append(f"\n## 业绩预告")
        user_parts.append(f"- 类型: {forecast.get('type','')}")
        user_parts.append(f"- 增幅: {forecast.get('p_change_min',0):.1f}% ~ {forecast.get('p_change_max',0):.1f}%")
        user_parts.append(f"- 净利区间: {forecast.get('net_profit_min',0)/1e8:.1f} ~ {forecast.get('net_profit_max',0)/1e8:.1f} 亿元")

    user_prompt = "\n".join(user_parts)
    return chat(FUNDAMENTAL_PROMPT, user_prompt, temperature=0.3, max_tokens=6000)


def run_trend_agent(data: Dict[str, Any]) -> str:
    """趋势分析 Agent。

    Args:
        data: 含 daily（日线 df）、daily_basic_now（PE/PB）、daily_basic_hist（PE/PB 历史）、code/name。
    """
    import pandas as pd

    name = data.get("name", "")
    code = data.get("code", "")
    daily = data.get("daily")
    basic = data.get("daily_basic_now", {})
    basic_hist = data.get("daily_basic_hist")

    user_parts = [f"# {name}({code}) 趋势数据\n"]

    # 均线数据
    if daily is not None and len(daily) >= 120:
        close = daily["close"]
        price = close.iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1]
        ma60_5d_ago = close.rolling(60).mean().iloc[-6]
        ma120_20d_ago = close.rolling(120).mean().iloc[-21]

        user_parts.append("## 均线系统")
        user_parts.append(f"- 当前价: {price:.2f}")
        user_parts.append(f"- MA20: {ma20:.2f}（乖离 {(price-ma20)/ma20*100:+.1f}%）")
        user_parts.append(f"- MA60: {ma60:.2f}（乖离 {(price-ma60)/ma60*100:+.1f}%）")
        user_parts.append(f"- MA120: {ma120:.2f}（乖离 {(price-ma120)/ma120*100:+.1f}%）")
        user_parts.append(f"- MA60 5日前: {ma60_5d_ago:.2f}（斜率{'↑' if ma60>ma60_5d_ago else '↓'}）")
        user_parts.append(f"- MA120 20日前: {ma120_20d_ago:.2f}（斜率{'↑' if ma120>ma120_20d_ago else '↓'}）")

        # 近期高低点
        user_parts.append(f"\n## 近期价格区间")
        user_parts.append(f"- 20日最高: {close.tail(20).max():.2f}")
        user_parts.append(f"- 20日最低: {close.tail(20).min():.2f}")
        user_parts.append(f"- 60日最高: {close.tail(60).max():.2f}")
        user_parts.append(f"- 60日最低: {close.tail(60).min():.2f}")

    # 估值数据
    pe = basic.get("pe", 0)
    pb = basic.get("pb", 0)
    user_parts.append(f"\n## 当前估值")
    user_parts.append(f"- PE: {pe:.1f}")
    user_parts.append(f"- PB: {pb:.2f}")

    # 估值分位
    if basic_hist is not None and len(basic_hist) >= 60:
        pe_series = basic_hist["pe"].dropna()
        pb_series = basic_hist["pb"].dropna()
        if not pe_series.empty and pe > 0:
            pe_pct = (pe_series < pe).sum() / len(pe_series) * 100
            user_parts.append(f"- PE 近3年分位: {pe_pct:.0f}%")
        if not pb_series.empty and pb > 0:
            pb_pct = (pb_series < pb).sum() / len(pb_series) * 100
            user_parts.append(f"- PB 近3年分位: {pb_pct:.0f}%")

    user_prompt = "\n".join(user_parts)
    return chat(TREND_PROMPT, user_prompt, temperature=0.3, max_tokens=5000)


def run_risk_agent(data: Dict[str, Any]) -> str:
    """风控分析 Agent。

    Args:
        data: 含 code/name、fina、forecast、financials、share_float、holder_trade。
    """
    name = data.get("name", "")
    code = data.get("code", "")
    fina = data.get("fina", {})
    forecast = data.get("forecast")
    financials = data.get("financials")
    share_float = data.get("share_float")

    user_parts = [f"# {name}({code}) 风控排查数据\n"]

    # 1. 业绩预告
    if forecast:
        user_parts.append(f"## 1. 业绩预告")
        user_parts.append(f"- 类型: {forecast.get('type','无')}")
        user_parts.append(f"- 净利区间: {forecast.get('net_profit_min',0)/1e8:.1f} ~ {forecast.get('net_profit_max',0)/1e8:.1f} 亿元")
    else:
        user_parts.append("## 1. 业绩预告: 无数据")

    # 2. 财务健康（来自 fina_indicator）
    latest = fina.get("latest", {})
    if latest:
        user_parts.append(f"\n## 2. 财务健康")
        user_parts.append(f"- 资产负债率: {latest.get('debt_to_assets',0):.1f}%")
        user_parts.append(f"- 速动比率: {latest.get('quick_ratio',0):.2f}")
        user_parts.append(f"- 流动比率: {latest.get('current_ratio',0):.2f}")

    # 3. 三大报表关键数据（商誉/现金流/应收）
    if financials:
        bs = financials.get("balance_sheet", {})
        if bs:
            user_parts.append(f"\n## 3. 资产负债表关键项")
            user_parts.append(f"- 商誉: {bs.get('goodwill',0)/1e8:.2f} 亿元")
            user_parts.append(f"- 商誉占净资产: {bs.get('goodwill_to_equity',0):.1f}%")
            user_parts.append(f"- 应收账款: {bs.get('accounts_receivable',0)/1e8:.2f} 亿元")
            user_parts.append(f"- 货币资金: {bs.get('cash',0)/1e8:.2f} 亿元")

        cf_list = financials.get("cashflow", [])
        if cf_list:
            user_parts.append(f"\n## 4. 现金流（近{len(cf_list)}季度）")
            for cf in cf_list[:4]:
                ocf = cf.get("operating_cf", 0)
                fcf = cf.get("free_cashflow", 0)
                user_parts.append(f"- {cf['period']}: 经营CF={ocf/1e8:.1f}亿 自由CF={fcf/1e8 if fcf else 0:.1f}亿")

    # 5. 限售解禁
    if share_float:
        ratio = share_float.get("total_float_ratio", 0)
        shares = share_float.get("total_float_shares", 0)
        user_parts.append(f"\n## 5. 限售解禁（未来90天）")
        if ratio > 0:
            user_parts.append(f"- 解禁比例: {ratio:.2f}%（{'高风险' if ratio>10 else '可控'}）")
            user_parts.append(f"- 解禁股数: {shares/1e4:.0f} 万股")
            for d in share_float.get("details", [])[:3]:
                user_parts.append(f"  - {d['date']}: {d['shares']/1e4:.0f}万股 ({d['ratio']:.2f}%)")
        else:
            user_parts.append("- 未来90天无解禁")
    else:
        user_parts.append(f"\n## 5. 限售解禁: 数据不足")

    # 6. 股东增减持
    holder = data.get("holder_trade")
    if holder:
        net = holder.get("net_buy", 0)
        user_parts.append(f"\n## 6. 股东增减持（近90天）")
        user_parts.append(f"- 净增减持: {net/1e4:.2f} 亿元（{'增持' if net>0 else '减持'}）")
    else:
        user_parts.append(f"\n## 6. 股东增减持: 数据不足")

    # ROE 趋势
    trend = fina.get("trend", [])
    if trend:
        user_parts.append(f"\n## ROE 趋势（近4季度）")
        for q in trend:
            user_parts.append(f"- {q['period']}: ROE={q.get('roe',0):.2f}%")

    user_prompt = "\n".join(user_parts)
    return chat(RISK_PROMPT, user_prompt, temperature=0.3, max_tokens=5000)


def run_bull_researcher(
    fundamental_report: str,
    trend_report: str,
    risk_report: str,
    name: str,
    code: str,
) -> str:
    """多头研究员。"""
    user_prompt = f"""# {name}({code}) 分析师报告汇总

## 基本面报告
{fundamental_report}

## 趋势报告
{trend_report}

## 风控报告
{risk_report}

---

请基于以上报告，构建你的看多论据。"""
    return chat(BULL_PROMPT, user_prompt, temperature=0.5, max_tokens=5000)


def run_bear_researcher(
    fundamental_report: str,
    trend_report: str,
    risk_report: str,
    name: str,
    code: str,
) -> str:
    """空头研究员。"""
    user_prompt = f"""# {name}({code}) 分析师报告汇总

## 基本面报告
{fundamental_report}

## 趋势报告
{trend_report}

## 风控报告
{risk_report}

---

请基于以上报告，构建你的看空论据。"""
    return chat(BEAR_PROMPT, user_prompt, temperature=0.5, max_tokens=5000)


def run_investment_manager(
    code: str,
    name: str,
    fundamental_report: str,
    trend_report: str,
    risk_report: str,
    bull_case: str,
    bear_case: str,
) -> Dict[str, Any]:
    """投资经理：综合所有报告和辩论，输出 JSON 格式最终决策。"""
    user_prompt = f"""# {name}({code}) 投资决策会议

## 基本面报告
{fundamental_report}

## 趋势报告
{trend_report}

## 风控报告
{risk_report}

## 多头研究员论据
{bull_case}

## 空头研究员论据
{bear_case}

---

请综合以上所有信息，做出最终投资决策。"""
    result = chat(MANAGER_PROMPT, user_prompt, temperature=0.3, max_tokens=6000)

    # 尝试解析 JSON
    try:
        # 找 JSON 块
        if "```json" in result:
            json_str = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            json_str = result.split("```")[1].split("```")[0].strip()
        else:
            json_str = result.strip()
        return json.loads(json_str)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning(f"[ML-Agent] 投资经理 JSON 解析失败: {e}")
        return {
            "ticker": code,
            "name": name,
            "rating": "Hold",
            "confidence": "低",
            "verdict": result,  # 返回原始文本
            "error": "JSON parse failed",
        }
