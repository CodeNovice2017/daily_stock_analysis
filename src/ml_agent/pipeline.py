# -*- coding: utf-8 -*-
"""中长线个股分析编排：串联数据准备 → 三个分析师 → 多空辩论 → 投资经理。

使用方式：
    from src.ml_agent.pipeline import analyze_stock

    result = analyze_stock('600089')
    print(result['verdict'])
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def analyze_stock(
    code: str,
    *,
    verbose: bool = True,
) -> Dict[str, Any]:
    """对单只股票执行完整的中长线深度分析。

    流程：
        1. 数据准备（Tushare 三表 + daily_basic + 日线）
        2. 基本面 Agent / 趋势 Agent / 风控 Agent（串行，每个 ~10s）
        3. 多头研究员 + 空头研究员（辩论）
        4. 投资经理（最终决策 JSON）

    Args:
        code: 股票代码（如 '600089'）。
        verbose: 打印进度。

    Returns:
        包含所有 Agent 报告和最终决策的 dict。
    """
    from .screener.data_provider import MLDataProvider
    from .agents.analysts import (
        run_fundamental_agent,
        run_trend_agent,
        run_risk_agent,
        run_bull_researcher,
        run_bear_researcher,
        run_investment_manager,
    )

    dp = MLDataProvider()
    t0 = time.time()

    # ── Step 1: 数据准备 ──
    if verbose:
        logger.info(f"[ML-Analyze] {code} 开始数据准备...")

    name = dp.get_stock_name(code) or code
    fina = dp.get_fina_indicator_full(code, n=4) or {}
    daily = dp.get_daily_data(code, days=250)
    basic = dp.get_daily_basic_valuation(code) or {}
    basic_hist = dp.get_daily_basic_history(code, days=500)
    forecast = dp.get_forecast(code)
    financials = dp.get_financial_statements(code, n=4)
    share_float = dp.get_share_float(code, days=90)
    holder_trade = dp.get_holder_trade(code)

    data = {
        "code": code,
        "name": name,
        "fina": fina,
        "daily": daily,
        "daily_basic_now": basic,
        "daily_basic_hist": basic_hist,
        "forecast": forecast,
        "financials": financials,
        "share_float": share_float,
        "holder_trade": holder_trade,
    }

    if verbose:
        logger.info(f"[ML-Analyze] {code} {name} 数据准备完成，启动 Agent 链")

    # ── Step 2: 三个分析师（串行，避免 API 并发限制）──
    if verbose:
        logger.info(f"[ML-Analyze] {code} → 基本面 Agent")
    fundamental_report = run_fundamental_agent(data)

    if verbose:
        logger.info(f"[ML-Analyze] {code} → 趋势 Agent")
    trend_report = run_trend_agent(data)

    if verbose:
        logger.info(f"[ML-Analyze] {code} → 风控 Agent")
    risk_report = run_risk_agent(data)

    # ── Step 3: 多空辩论 ──
    if verbose:
        logger.info(f"[ML-Analyze] {code} → 多空辩论")
    bull_case = run_bull_researcher(fundamental_report, trend_report, risk_report, name, code)
    bear_case = run_bear_researcher(fundamental_report, trend_report, risk_report, name, code)

    # ── Step 4: 投资经理最终决策 ──
    if verbose:
        logger.info(f"[ML-Analyze] {code} → 投资经理决策")
    decision = run_investment_manager(
        code, name,
        fundamental_report, trend_report, risk_report,
        bull_case, bear_case,
    )

    elapsed = time.time() - t0
    if verbose:
        logger.info(
            f"[ML-Analyze] {code} {name} 完成, "
            f"评级={decision.get('rating','?')}, "
            f"耗时 {elapsed:.0f}s"
        )

    return {
        "code": code,
        "name": name,
        "decision": decision,
        "reports": {
            "fundamental": fundamental_report,
            "trend": trend_report,
            "risk": risk_report,
            "bull": bull_case,
            "bear": bear_case,
        },
        "elapsed_seconds": round(elapsed, 1),
    }


def format_report(result: Dict[str, Any]) -> str:
    """将分析结果格式化为可读的 Markdown 报告。"""
    decision = result.get("decision", {})
    reports = result.get("reports", {})
    name = result.get("name", "")
    code = result.get("code", "")

    lines = [
        f"# {name}({code}) 中长线分析报告",
        f"",
        f"## 最终决策",
        f"",
        f"- **评级**: {decision.get('rating', 'N/A')}",
        f"- **信心度**: {decision.get('confidence', 'N/A')}",
        f"- **投资周期**: {decision.get('timeframe', 'N/A')}",
        f"- **基本面评分**: {decision.get('fundamental_score', 'N/A')}",
        f"- **趋势评分**: {decision.get('trend_score', 'N/A')}",
        f"- **风险等级**: {decision.get('risk_level', 'N/A')}",
        f"",
        f"### 综合判断",
        f"{decision.get('verdict', 'N/A')}",
        f"",
        f"### 操作计划",
        f"",
    ]

    action = decision.get("action_plan", {})
    if action:
        lines.append(f"| 项目 | 价位 |")
        lines.append(f"|------|------|")
        lines.append(f"| 入场区间 | {action.get('entry_zone', 'N/A')} |")
        lines.append(f"| 加仓区间 | {action.get('add_zone', 'N/A')} |")
        lines.append(f"| 止损位 | {action.get('stop_loss', 'N/A')} |")
        lines.append(f"| 目标位1 | {action.get('target_1', 'N/A')} |")
        lines.append(f"| 目标位2 | {action.get('target_2', 'N/A')} |")
        lines.append(f"| 仓位建议 | {action.get('position_size', 'N/A')} |")

    lines.extend([
        f"",
        f"### 多空辩论",
        f"",
        f"**多头核心论据**:",
        f"{decision.get('bull_case', 'N/A')}",
        f"",
        f"**空头核心论据**:",
        f"{decision.get('bear_case', 'N/A')}",
        f"",
        f"---",
        f"",
        f"### 基本面报告",
        f"",
        reports.get("fundamental", "N/A"),
        f"",
        f"### 趋势报告",
        f"",
        reports.get("trend", "N/A"),
        f"",
        f"### 风控报告",
        f"",
        reports.get("risk", "N/A"),
        f"",
        f"*分析耗时: {result.get('elapsed_seconds', 0):.0f}s*",
    ])

    return "\n".join(lines)
