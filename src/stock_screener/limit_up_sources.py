# -*- coding: utf-8 -*-
"""
涨停池数据源：优先 Tushare（limit_list_d），兜底 AKShare（stock_zt_pool_em）。

不修改上游 TushareFetcher，在本模块内直接调用 tushare SDK（用 config 里的 token）。
统一输出标准化列表，字段对齐 service 层 upsert_record 入参。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def fetch_limit_up_pool(scan_date: date, n: int = 200) -> List[Dict[str, Any]]:
    """获取涨停池，Tushare 优先，失败兜底 AKShare（走上游 DataFetcherManager）。"""
    rows = _fetch_via_tushare(scan_date, n)
    if rows:
        logger.info("涨停池数据源: Tushare, %d 只", len(rows))
        return rows

    logger.info("Tushare 涨停池无数据，回退 AKShare")
    rows = _fetch_via_akshare(scan_date, n)
    if rows:
        logger.info("涨停池数据源: AKShare, %d 只", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Tushare（优先）
# ---------------------------------------------------------------------------

def _fetch_via_tushare(scan_date: date, n: int) -> List[Dict[str, Any]]:
    """通过 Tushare limit_list_d 接口获取涨停个股。"""
    try:
        from src.config import get_config
        token = get_config().tushare_token
        if not token:
            return []
        import tushare as ts
        pro = ts.pro_api(token)
        date_str = scan_date.strftime("%Y%m%d")

        df = pro.limit_list_d(
            trade_date=date_str,
            limit_type="U",
            fields="trade_date,ts_code,name,industry,close,pct_chg,amount,"
                   "first_time,last_time,open_times,up_stat,limit_times,float_mv,turnover_ratio",
        )
        if df is None or df.empty:
            return []

        rows: List[Dict[str, Any]] = []
        for _, r in df.iterrows():
            ts_code = str(r.get("ts_code", ""))
            code = ts_code.split(".")[0] if "." in ts_code else ts_code
            if not code:
                continue
            rows.append({
                "code": code,
                "name": str(r.get("name", "")).strip(),
                "price": _f(r.get("close")),
                "change_pct": _f(r.get("pct_chg")),
                "amount": _f(r.get("amount")),
                "consecutive_boards": int(r.get("limit_times") or 1),
                "industry": str(r.get("industry", "")).strip(),
                "break_count": int(r.get("open_times") or 0),
                "first_limit_time": str(r.get("first_time", "")).strip(),
                "last_limit_time": str(r.get("last_time", "")).strip(),
                "turnover_rate": _f(r.get("turnover_ratio")),
                "float_mv": _f(r.get("float_mv")),
                "up_stat": str(r.get("up_stat", "")).strip(),
                "source": "tushare",
            })
        # 按连板数降序、首封时间升序排序
        rows.sort(key=lambda x: (-x.get("consecutive_boards", 1), x.get("first_limit_time", "9")))
        return rows[:n]
    except Exception as e:
        logger.warning("Tushare 涨停池获取失败: %s", e)
        return []


# ---------------------------------------------------------------------------
# AKShare（兜底，复用上游 DataFetcherManager）
# ---------------------------------------------------------------------------

def _fetch_via_akshare(scan_date: date, n: int) -> List[Dict[str, Any]]:
    """复用上游 DataFetcherManager.get_limit_up_pool()。"""
    try:
        from data_provider.base import DataFetcherManager
        dm = DataFetcherManager()
        date_str = scan_date.strftime("%Y%m%d")
        raw = dm.get_limit_up_pool(date=date_str, n=n)
        if not raw:
            return []
        # 上游字段已基本对齐，补 source 标记
        for item in raw:
            item["source"] = "akshare"
        return raw
    except Exception as e:
        logger.warning("AKShare 涨停池获取失败: %s", e)
        return []


def _f(v) -> Optional[float]:
    try:
        if v is None:
            return None
        val = float(v)
        return val if val == val else None  # NaN 检查
    except (TypeError, ValueError):
        return None
