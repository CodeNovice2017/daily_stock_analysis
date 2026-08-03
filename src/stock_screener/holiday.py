# -*- coding: utf-8 -*-
"""
A 股交易日历，基于 holiday-cn 项目（https://github.com/NateScarlet/holiday-cn）。

判定规则（A 股市场）：
  - 周一至周五 且 非法定假日(isOffDay=true) → 交易日
  - 周末调休补班(isOffDay=false) → 政府工作日，但 A 股不开市 → 非交易日
  - 法定假日(isOffDay=true) → 非交易日

数据本地缓存到 data/stock_screener/holidays/，避免重复请求。
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Set
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

HOLIDAY_CN_BASE = "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master"
_CACHE_DIR = Path("data/stock_screener/holidays")
_HOLIDAYS_CACHE: dict[int, Set[str]] = {}  # year -> set of "YYYY-MM-DD"


def _cache_path(year: int) -> Path:
    return _CACHE_DIR / f"{year}.json"


def _load_year(year: int) -> Set[str]:
    """加载某年的法定假日集合（isOffDay=true 的日期）。"""
    if year in _HOLIDAYS_CACHE:
        return _HOLIDAYS_CACHE[year]

    cache_file = _cache_path(year)
    data = None

    # 1. 先尝试本地缓存
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            logger.debug("使用本地缓存的 %d 年假日数据", year)
        except Exception as e:
            logger.debug("本地缓存 %d 解析失败: %s", year, e)

    # 2. 缓存缺失则从 GitHub 拉取
    if data is None:
        url = f"{HOLIDAY_CN_BASE}/{year}.json"
        try:
            req = Request(url, headers={"User-Agent": "stock-screener/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("已拉取并缓存 %d 年假日数据: %s", year, cache_file)
        except Exception as e:
            logger.warning("拉取 %d 年假日数据失败: %s（回退到纯周末判断）", year, e)
            _HOLIDAYS_CACHE[year] = set()
            return _HOLIDAYS_CACHE[year]

    holidays = {
        d["date"] for d in data.get("days", []) if d.get("isOffDay") is True
    }
    _HOLIDAYS_CACHE[year] = holidays
    return holidays


def is_trading_day(d: date) -> bool:
    """判断是否为 A 股交易日。"""
    # 周末一律不开市（含调休补班，A 股不跟随政府调休）
    if d.weekday() >= 5:
        return False
    holidays = _load_year(d.year)
    return d.isoformat() not in holidays


def latest_trading_day_on_or_before(d: date) -> date:
    """返回 d 当天或之前最近的交易日。"""
    cur = d
    for _ in range(15):  # 最多回退两周
        if is_trading_day(cur):
            return cur
        cur -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    """返回 d 之后的下一个交易日。"""
    cur = d + timedelta(days=1)
    for _ in range(15):
        if is_trading_day(cur):
            return cur
        cur += timedelta(days=1)
    return cur


def trading_days_after(start: date, n: int) -> list[date]:
    """返回 start 之后的 n 个交易日（不含 start 本身）。"""
    result: list[date] = []
    cur = start
    for _ in range(n + 15):
        cur = next_trading_day(cur)
        result.append(cur)
        if len(result) >= n:
            break
    return result[:n]


def is_target_evaluable(limit_up_date: date, track_days: int, as_of: Optional[date] = None) -> bool:
    """判断某涨停记录截至 as_of 是否已凑够 track_days 个后续交易日。"""
    ref = as_of or date.today()
    needed = trading_days_after(limit_up_date, track_days)
    if not needed:
        return False
    # 最后一个需要的交易日必须 <= ref（即当天或之前已完成）
    return needed[-1] <= ref
