# -*- coding: utf-8 -*-
"""中长线模块专用数据适配层。

在 TushareFetcher 之上封装，拉取 scorer 所需的扩展字段。
不修改 DSA 现有的 ``get_fina_indicator`` 方法，保持模块独立性。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from data_provider.tushare_fetcher import TushareFetcher
from .realtime_types_compat import safe_float

logger = logging.getLogger(__name__)


class MLDataProvider:
    """中长线模块数据提供者，封装 TushareFetcher。

    比 DSA 的 ``get_fina_indicator`` 多拉取增速字段（or_yoy/netprofit_yoy/q_profit_yoy），
    并提供日线 + daily_basic 历史的批量获取。
    """

    def __init__(self, fetcher: Optional[TushareFetcher] = None):
        if fetcher is not None:
            self._fetcher = fetcher
        else:
            from src.config import get_config
            # [personal patch] P1-B3：透传限频配置
            rate_limit = getattr(get_config(), "tushare_rate_limit_per_minute", 80)
            self._fetcher = TushareFetcher(rate_limit_per_minute=rate_limit)
        if self._fetcher._api is None:
            raise RuntimeError("TushareFetcher 未初始化，请检查 TUSHARE_TOKEN")
        # [personal patch] P2：指数日线实例级缓存（残差动量基准，全流程拉一次）
        self._index_daily_cache: Optional[pd.DataFrame] = None

    @property
    def fetcher(self) -> TushareFetcher:
        return self._fetcher

    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """全市场股票列表。"""
        return self._fetcher.get_stock_list()

    def get_stock_name(self, code: str) -> Optional[str]:
        """股票名称。"""
        return self._fetcher.get_stock_name(code)

    def get_daily_data(self, code: str, days: int = 180) -> Optional[pd.DataFrame]:
        """日线 OHLCV 数据（含 MA 计算）。

        复用 BaseFetcher.get_daily_data，返回含 close/volume 列的 DataFrame。
        """
        return self._fetcher.get_daily_data(code, days=days)

    def get_daily_basic_valuation(self, code: str) -> Optional[Dict[str, float]]:
        """当日 PE/PB/市值。"""
        return self._fetcher.get_daily_basic_valuation(code)

    def get_daily_basic_history(
        self, code: str, days: int = 500
    ) -> Optional[pd.DataFrame]:
        """PE/PB 历史数据（用于计算估值分位）。

        拉取近 ``days`` 天的 daily_basic，含 trade_date/pe/pb 列。
        """
        ts_code = self._fetcher._convert_stock_code(code)
        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        try:
            df = self._fetcher._call_api_with_rate_limit(
                "daily_basic",
                ts_code=ts_code,
                start_date=start,
                end_date=today,
                fields="ts_code,trade_date,pe,pb,total_mv,circ_mv",
            )
            if df is not None and not df.empty:
                df = df.sort_values("trade_date").reset_index(drop=True)
            return df
        except Exception as e:
            logger.debug(f"[ML-Data] daily_basic 历史获取失败 {code}: {e}")
            return None

    def get_fina_indicator_full(self, code: str, n: int = 4) -> Optional[Dict[str, Any]]:
        """扩展版财务指标，包含增速字段。

        比DSA的 get_fina_indicator 多返回：
            - or_yoy: 营收同比增速 (%)
            - netprofit_yoy: 净利润同比增速 (%)
            - q_profit_yoy: 单季净利润同比增速 (%)
            - roa: 总资产收益率
            - eps: 每股收益
            - bps: 每股净资产
            - current_ratio: 流动比率
            - quick_ratio: 速动比率
        """
        ts_code = self._fetcher._convert_stock_code(code)
        try:
            df = self._fetcher._call_api_with_rate_limit(
                "fina_indicator",
                ts_code=ts_code,
                fields=(
                    "ts_code,ann_date,end_date,"
                    "roe,roe_waa,roa,"
                    "grossprofit_margin,netprofit_margin,"
                    "debt_to_assets,current_ratio,quick_ratio,"
                    "dt_netprofit,dt_roe,q_profit_yoy,"
                    "netprofit_yoy,or_yoy,"
                    "eps,bps"
                ),
            )
            if df is None or df.empty:
                return None

            recent = df.sort_values("end_date", ascending=False).head(n)
            quarters = []
            for _, row in recent.iterrows():
                quarters.append({
                    "period": str(row.get("end_date", "")),
                    "roe": safe_float(row.get("roe")),
                    "roa": safe_float(row.get("roa")),
                    "grossprofit_margin": safe_float(row.get("grossprofit_margin")),
                    "netprofit_margin": safe_float(row.get("netprofit_margin")),
                    "debt_to_assets": safe_float(row.get("debt_to_assets")),
                    "current_ratio": safe_float(row.get("current_ratio")),
                    "quick_ratio": safe_float(row.get("quick_ratio")),
                    "or_yoy": safe_float(row.get("or_yoy")),
                    "netprofit_yoy": safe_float(row.get("netprofit_yoy")),
                    "q_profit_yoy": safe_float(row.get("q_profit_yoy")),
                    "eps": safe_float(row.get("eps")),
                    "bps": safe_float(row.get("bps")),
                })

            latest = quarters[0] if quarters else {}
            prev = quarters[1] if len(quarters) > 1 else {}
            roe_now = latest.get("roe", 0)
            roe_prev = prev.get("roe", 0)

            # 扁平化最新季度数据，供 scorer 直接使用
            flat = dict(latest)
            flat["latest"] = latest
            flat["trend"] = quarters
            flat["roe"] = roe_now
            flat["roe_trend"] = (
                "up" if roe_now and roe_prev and roe_now > roe_prev
                else "down" if roe_now and roe_prev and roe_now < roe_prev
                else "stable"
            )
            return flat

        except Exception as e:
            logger.debug(f"[ML-Data] fina_indicator 扩展获取失败 {code}: {e}")
            return None

    def get_index_daily(self, days: int = 300) -> Optional[pd.DataFrame]:
        """基准指数日线（沪深300），实例级缓存——整个筛选流程只拉一次。

        [personal patch] P2：残差动量需要市场基准；返回 date/close 列，
        date 为 datetime 类型，与个股日线按日期对齐。
        """
        if self._index_daily_cache is not None:
            return self._index_daily_cache
        try:
            df = self._fetcher._call_api_with_rate_limit(
                "index_daily",
                ts_code="000300.SH",
                start_date=(datetime.now() - timedelta(days=int(days * 1.8) + 15)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
                fields="ts_code,trade_date,close",
            )
            if df is None or df.empty:
                return None
            df = df.sort_values("trade_date").reset_index(drop=True)
            df = df.rename(columns={"trade_date": "date"})
            df["date"] = pd.to_datetime(df["date"])
            self._index_daily_cache = df
            return df
        except Exception as e:
            logger.debug(f"[ML-Data] 指数日线获取失败: {e}")
            return None

    def get_single_quarter_profits(self, code: str, n_periods: int = 10) -> Optional[List[float]]:
        """单季净利润序列（时间升序），由累计值差分而来。

        [personal patch] P2：时序 SUE 需要 5-9 期单季净利润；
        income 接口的 n_income 为年初至今累计值，Q2=H1-Q1 依此差分。
        """
        ts_code = self._fetcher._convert_stock_code(code)
        try:
            df = self._fetcher._call_api_with_rate_limit(
                "income",
                ts_code=ts_code,
                fields="ts_code,end_date,n_income",
            )
            if df is None or df.empty:
                return None
            df = df.sort_values("end_date").reset_index(drop=True)
            quarters: List[float] = []
            prev_end: Optional[str] = None
            prev_cum: Optional[float] = None
            for _, r in df.iterrows():
                end = str(r.get("end_date", ""))
                cum = safe_float(r.get("n_income"))
                if prev_end is None or prev_cum is None:
                    quarters.append(cum)
                else:
                    # 同年后一期 = 累计差分；新一年的 Q1（0331）本身就是单季
                    if end[4:6] == "03":
                        quarters.append(cum)
                    else:
                        quarters.append(cum - prev_cum)
                prev_end, prev_cum = end, cum
                if len(quarters) >= n_periods:
                    break
            return quarters if len(quarters) >= 5 else None
        except Exception as e:
            logger.debug(f"[ML-Data] 单季净利序列获取失败 {code}: {e}")
            return None

    def get_cashflow_ratio(self, code: str) -> Optional[float]:
        """现金流实现率：最近报告期 经营现金流累计 / 净利润累计。

        [personal patch] P2：Sloan 应计异象的镜像——利润是否有现金背书。
        亏损时净利 ≤ 0 无法计算有意义的比率，返回 None（不计分不惩罚）。
        """
        ts_code = self._fetcher._convert_stock_code(code)
        try:
            df_cf = self._fetcher._call_api_with_rate_limit(
                "cashflow", ts_code=ts_code,
                fields="ts_code,end_date,n_cashflow_act",
            )
            if df_cf is None or df_cf.empty:
                return None
            latest_cf = df_cf.sort_values("end_date", ascending=False).iloc[0]
            end_date = str(latest_cf.get("end_date", ""))
            ocf = safe_float(latest_cf.get("n_cashflow_act"))
            if not end_date:
                return None
            df_inc = self._fetcher._call_api_with_rate_limit(
                "income", ts_code=ts_code,
                fields="ts_code,end_date,n_income",
            )
            if df_inc is None or df_inc.empty:
                return None
            inc_rows = df_inc[df_inc["end_date"] == end_date]
            if inc_rows.empty:
                return None
            ni = safe_float(inc_rows.iloc[0].get("n_income"))
            if ni <= 0:
                return None
            return ocf / ni
        except Exception as e:
            logger.debug(f"[ML-Data] 现金流实现率获取失败 {code}: {e}")
            return None

    def get_financial_statements(self, code: str, n: int = 4) -> Optional[Dict[str, Any]]:
        """获取三大财务报表最近 n 个季度的关键数据。

        数据来源：Tushare income/balancesheet/cashflow（5000 积分）。
        用于补充 fina_indicator 无法覆盖的字段：
            - 利润表：营收、净利润绝对值
            - 资产负债表：商誉、应收账款、货币资金、总资产、总负债
            - 现金流量表：经营现金流、自由现金流
        """
        ts_code = self._fetcher._convert_stock_code(code)
        result: Dict[str, Any] = {}

        try:
            # 利润表
            df_inc = self._fetcher._call_api_with_rate_limit(
                "income", ts_code=ts_code,
                fields="ts_code,end_date,revenue,n_income,n_income_attr_p,operate_profit",
            )
            if df_inc is not None and not df_inc.empty:
                recent_inc = df_inc.sort_values("end_date", ascending=False).head(n)
                result["income"] = [
                    {
                        "period": str(r.get("end_date", "")),
                        "revenue": safe_float(r.get("revenue")),
                        "n_income": safe_float(r.get("n_income")),
                    }
                    for _, r in recent_inc.iterrows()
                ]

            # 资产负债表
            df_bs = self._fetcher._call_api_with_rate_limit(
                "balancesheet", ts_code=ts_code,
                fields="ts_code,end_date,total_assets,total_liab,goodwill,accounts_rece,money_cap,total_hldr_eqy_exc_min_int",
            )
            if df_bs is not None and not df_bs.empty:
                latest_bs = df_bs.sort_values("end_date", ascending=False).iloc[0]
                goodwill = safe_float(latest_bs.get("goodwill"))
                total_assets = safe_float(latest_bs.get("total_assets"))
                total_equity = safe_float(latest_bs.get("total_hldr_eqy_exc_min_int"))
                result["balance_sheet"] = {
                    "total_assets": total_assets,
                    "total_liab": safe_float(latest_bs.get("total_liab")),
                    "goodwill": goodwill,
                    "goodwill_to_equity": goodwill / total_equity * 100 if total_equity > 0 else 0,
                    "accounts_receivable": safe_float(latest_bs.get("accounts_rece")),
                    "cash": safe_float(latest_bs.get("money_cap")),
                }

            # 现金流量表
            df_cf = self._fetcher._call_api_with_rate_limit(
                "cashflow", ts_code=ts_code,
                fields="ts_code,end_date,n_cashflow_act,n_cashflow_inv_act,free_cashflow",
            )
            if df_cf is not None and not df_cf.empty:
                recent_cf = df_cf.sort_values("end_date", ascending=False).head(n)
                result["cashflow"] = [
                    {
                        "period": str(r.get("end_date", "")),
                        "operating_cf": safe_float(r.get("n_cashflow_act")),
                        "investing_cf": safe_float(r.get("n_cashflow_inv_act")),
                        "free_cashflow": safe_float(r.get("free_cashflow")),
                    }
                    for _, r in recent_cf.iterrows()
                ]

            return result if result else None

        except Exception as e:
            logger.debug(f"[ML-Data] 三表获取失败 {code}: {e}")
            return None

    def get_share_float(self, code: str, days: int = 90) -> Optional[Dict[str, Any]]:
        """限售股解禁（未来 days 天内）。

        返回 ``{total_float_shares, total_float_ratio, details}``。
        """
        ts_code = self._fetcher._convert_stock_code(code)
        today = datetime.now().strftime("%Y%m%d")
        end = (datetime.now() + timedelta(days=days)).strftime("%Y%m%d")
        try:
            df = self._fetcher._call_api_with_rate_limit(
                "share_float", ts_code=ts_code,
                start_date=today, end_date=end,
            )
            if df is None or df.empty:
                return {"total_float_shares": 0, "total_float_ratio": 0, "details": []}

            total_shares = df["float_share"].sum() if "float_share" in df.columns else 0
            total_ratio = df["float_ratio"].sum() if "float_ratio" in df.columns else 0
            details = [
                {
                    "date": str(r.get("float_date", "")),
                    "shares": safe_float(r.get("float_share")),
                    "ratio": safe_float(r.get("float_ratio")),
                }
                for _, r in df.iterrows()
            ]
            return {
                "total_float_shares": total_shares,
                "total_float_ratio": total_ratio,
                "details": details,
            }
        except Exception as e:
            logger.debug(f"[ML-Data] 解禁数据获取失败 {code}: {e}")
            return None

    def get_holder_trade(self, code: str) -> Optional[Dict[str, Any]]:
        """股东增减持（近 90 天）。"""
        ts_code = self._fetcher._convert_stock_code(code)
        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        try:
            df = self._fetcher._call_api_with_rate_limit(
                "stk_holdertrade",
                ts_code=ts_code,
                start_date=start,
                end_date=today,
            )
            if df is None or df.empty:
                return None
            # 计算净增持（万元）
            if "change" in df.columns:
                net = df["change"].sum()
            else:
                net = 0
            return {"net_buy": safe_float(net)}
        except Exception as e:
            logger.debug(f"[ML-Data] 股东增减持获取失败 {code}: {e}")
            return None

    def get_hk_hold_change(self, code: str) -> Optional[float]:
        """北向持股比例变化（近 30 天，百分点）。"""
        ts_code = self._fetcher._convert_stock_code(code)
        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=35)).strftime("%Y%m%d")
        try:
            df = self._fetcher._call_api_with_rate_limit(
                "hk_hold",
                code=ts_code,
                start_date=start,
                end_date=today,
            )
            if df is None or df.empty or "vol" not in df.columns:
                return None
            if len(df) < 2:
                return None
            latest = df.sort_values("trade_date").iloc[-1]["vol"]
            earliest = df.sort_values("trade_date").iloc[0]["vol"]
            # 返回持股比例变化（百分点近似）
            return safe_float(latest - earliest)
        except Exception as e:
            logger.debug(f"[ML-Data] 北向持股获取失败 {code}: {e}")
            return None

    def get_forecast(self, code: str):
        """业绩预告。"""
        return self._fetcher.get_forecast(code)

    def has_recent_research(self, code: str, days: int = 90) -> bool:
        """近期是否有机构调研。"""
        ts_code = self._fetcher._convert_stock_code(code)
        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        try:
            df = self._fetcher._call_api_with_rate_limit(
                "stk_surv",
                ts_code=ts_code,
                start_date=start,
                end_date=today,
            )
            return df is not None and not df.empty
        except Exception as e:
            logger.debug(f"[ML-Data] 调研数据获取失败 {code}: {e}")
            return False
