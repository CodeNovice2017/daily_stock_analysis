# -*- coding: utf-8 -*-
"""选股引擎编排：串联三层筛选 + 评分 + 排序。

使用方式：
    from src.ml_agent.screener.engine import MLScreener

    screener = MLScreener()
    results = screener.run(top_n=30)
    for r in results:
        print(f"{r.code} {r.name} | 总分 {r.total_score} | {r.highlights}")
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from .data_provider import MLDataProvider
from .filters import ScreenResult, filter_hard, filter_trend
from .scorer import score_stock

logger = logging.getLogger(__name__)

_RATE_LIMIT_SLEEP = 0.3  # Tushare API 调用间隔（秒）


class MLScreener:
    """中长线选股引擎。

    数据全部来自 Tushare 5000 积分接口，通过 ``MLDataProvider`` 封装。
    """

    def __init__(self, data_provider: Optional[MLDataProvider] = None):
        """
        Args:
            data_provider: ``MLDataProvider`` 实例。不传则自动创建。
        """
        self._dp = data_provider or MLDataProvider()
        self._stats: Dict[str, int] = {}

    def run(
        self,
        top_n: int = 30,
        codes: Optional[List[str]] = None,
        verbose: bool = True,
    ) -> List[ScreenResult]:
        """执行完整的三层筛选 + 评分流程。

        Args:
            top_n: 返回前 N 只，按总分降序。
            codes: 指定股票池（调试用），None 则全市场扫描。
            verbose: 打印进度日志。

        Returns:
            ``ScreenResult`` 列表，按总分降序排列。
        """
        dp = self._dp
        t0 = time.time()

        # ── Step 0: 获取股票列表 ──
        stock_list = dp.get_stock_list()
        if stock_list is None or stock_list.empty:
            logger.error("[ML-Screen] 无法获取股票列表")
            return []

        if codes:
            stock_list = stock_list[stock_list["code"].isin(codes)]

        total_universe = len(stock_list)
        if verbose:
            logger.info(f"[ML-Screen] 开始扫描 {total_universe} 只股票")

        # ── Step 1: 批量拉取 daily_basic + fina_indicator ──
        daily_basic_map: Dict[str, Dict[str, float]] = {}
        fina_map: Dict[str, Dict[str, Any]] = {}

        for i, (_, row) in enumerate(stock_list.iterrows()):
            code = row["code"]
            try:
                basic = dp.get_daily_basic_valuation(code)
                if basic:
                    daily_basic_map[code] = basic

                fina = dp.get_fina_indicator_full(code, n=4)
                if fina:
                    fina_map[code] = fina
            except Exception as e:
                logger.debug(f"[ML-Screen] {code} 数据获取失败: {e}")

            if (i + 1) % 100 == 0 and verbose:
                logger.info(f"[ML-Screen] 数据拉取进度: {i+1}/{total_universe}")
            time.sleep(_RATE_LIMIT_SLEEP)

        # ── Step 2: 第一层硬性过滤 ──
        passed_l1 = filter_hard(stock_list, daily_basic_map, fina_map)
        self._stats["universe"] = total_universe
        self._stats["after_l1"] = len(passed_l1)

        # ── Step 3: 批量拉取日线数据 ──
        daily_map: Dict[str, pd.DataFrame] = {}
        for code in passed_l1:
            try:
                df = dp.get_daily_data(code, days=250)
                if df is not None and len(df) >= 120:
                    daily_map[code] = df
            except Exception as e:
                logger.debug(f"[ML-Screen] {code} 日线获取失败: {e}")
            time.sleep(_RATE_LIMIT_SLEEP)

        # ── Step 4: 第二层趋势筛选 ──
        passed_l2 = filter_trend(passed_l1, daily_map)
        self._stats["after_l2"] = len(passed_l2)

        if verbose:
            logger.info(f"[ML-Screen] 趋势筛选通过 {len(passed_l2)} 只，开始评分")

        # ── Step 5: 第三层综合评分 ──
        results: List[ScreenResult] = []
        for code in passed_l2:
            try:
                row = stock_list[stock_list["code"] == code].iloc[0]
                name = str(row.get("name", ""))
                industry = str(row.get("industry", ""))

                result = self._score_one(
                    dp, code, name, industry,
                    fina_map.get(code, {}),
                    daily_map.get(code),
                    daily_basic_map.get(code, {}),
                )
                results.append(result)
            except Exception as e:
                logger.debug(f"[ML-Screen] {code} 评分失败: {e}")

        # ── Step 6: 排序 ──
        results.sort(key=lambda r: r.total_score, reverse=True)
        results = results[:top_n]

        elapsed = time.time() - t0
        self._stats["final"] = len(results)
        if verbose:
            logger.info(
                f"[ML-Screen] 完成: {total_universe} → L1:{len(passed_l1)} → "
                f"L2:{len(passed_l2)} → Top{len(results)}, 耗时 {elapsed:.0f}s"
            )

        return results

    def run_for_codes(self, codes: List[str], verbose: bool = True) -> List[ScreenResult]:
        """对指定股票池做评分（不做硬性过滤和趋势筛选）。

        用于调试或对已知持仓/关注股进行评分。
        """
        dp = self._dp
        results: List[ScreenResult] = []

        for code in codes:
            try:
                name = dp.get_stock_name(code) or code
                fina = dp.get_fina_indicator_full(code, n=4) or {}
                daily = dp.get_daily_data(code, days=250)
                basic = dp.get_daily_basic_valuation(code) or {}
                basic_hist = dp.get_daily_basic_history(code, days=500)

                if daily is None or len(daily) < 60:
                    if verbose:
                        logger.warning(f"[ML-Screen] {code} 日线数据不足，跳过")
                    continue

                result = self._score_one(
                    dp, code, name, "", fina, daily, basic, basic_hist,
                )
                results.append(result)

                if verbose:
                    logger.info(
                        f"[ML-Screen] {code} {name}: "
                        f"总分 {result.total_score:.0f} "
                        f"(质量{result.quality_score:.0f}+成长{result.growth_score:.0f}"
                        f"+估值{result.valuation_score:.0f}+趋势{result.trend_score:.0f}"
                        f"+筹码{result.chip_score:.0f})"
                    )
            except Exception as e:
                logger.error(f"[ML-Screen] {code} 评分失败: {e}")
            time.sleep(_RATE_LIMIT_SLEEP)

        results.sort(key=lambda r: r.total_score, reverse=True)
        return results

    def _score_one(
        self,
        dp: MLDataProvider,
        code: str,
        name: str,
        industry: str,
        fina: Dict[str, Any],
        daily_df: pd.DataFrame,
        daily_basic_now: Dict[str, float],
        daily_basic_hist: Optional[pd.DataFrame] = None,
    ) -> ScreenResult:
        """单只股票评分，含筹码资金数据。"""
        # 筹码资金数据（可能为 None）
        try:
            holder_trade = dp.get_holder_trade(code)
        except Exception:
            holder_trade = None
        try:
            hk_change = dp.get_hk_hold_change(code)
        except Exception:
            hk_change = None
        try:
            surv_flag = dp.has_recent_research(code)
        except Exception:
            surv_flag = False

        return score_stock(
            code=code,
            name=name,
            industry=industry,
            fina=fina,
            daily_df=daily_df,
            daily_basic_now=daily_basic_now,
            daily_basic_hist=daily_basic_hist,
            holder_trade=holder_trade,
            hk_hold_change=hk_change,
            surv_flag=surv_flag,
        )

    def get_stats(self) -> Dict[str, int]:
        """返回最近一次 run 的统计信息。"""
        return self._stats

    @staticmethod
    def results_to_json(results: List[ScreenResult]) -> str:
        """将结果序列化为 JSON 字符串。"""
        return json.dumps(
            [r.to_dict() for r in results],
            ensure_ascii=False,
            indent=2,
        )
