# -*- coding: utf-8 -*-
"""[personal patch] P1-B1/B3：Tushare 财报 TTL 缓存与类级共享限频的单元测试。"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from data_provider.tushare_fetcher import TushareFetcher


@pytest.fixture
def fetcher():
    """跳过真实 API 初始化的最小实例。"""
    with patch.object(TushareFetcher, "_init_api", lambda self: None), \
         patch.object(TushareFetcher, "_determine_priority", lambda self: 2):
        f = TushareFetcher()
    f._api = object()  # 让 _call_api_with_rate_limit 通过非 None 检查
    return f


@pytest.fixture(autouse=True)
def _restore_shared_rate_counters():
    """类级共享计数器跨用例还原，避免状态泄漏拖慢/卡住后续测试。"""
    saved = (TushareFetcher._shared_call_count, TushareFetcher._shared_minute_start)
    yield
    TushareFetcher._shared_call_count, TushareFetcher._shared_minute_start = saved


def _fake_df(**cols):
    return pd.DataFrame(cols)


class TestFinaTTLCache:
    """财报缓存：二次调用不触发 API；TTL 过期后重新拉取。"""

    def test_get_forecast_cached_on_second_call(self, fetcher):
        calls = []
        df = _fake_df(
            ts_code=["000783.SZ"], ann_date=["20260701"], end_date=["20260630"],
            type=["预增"], p_change_min=[80.0], p_change_max=[90.0],
            net_profit_min=[3.126e10], net_profit_max=[3.3e10], summary=["x"],
        )
        with patch.object(
            fetcher, "_call_api_with_rate_limit", side_effect=lambda name, **kw: calls.append(name) or df
        ):
            r1 = fetcher.get_forecast("000783")
            r2 = fetcher.get_forecast("000783")
        assert r1 == r2
        assert r1["type"] == "预增"
        assert len(calls) == 1  # 第二次命中缓存

    def test_get_fina_indicator_cache_key_includes_n(self, fetcher):
        calls = []
        df = _fake_df(
            ts_code=["000783.SZ"] * 2, ann_date=["20260701", "20260401"],
            end_date=["20260630", "20260331"],
            roe=[4.5, 3.5], roa=[1.2, 1.0],
            grossprofit_margin=[40.0, 38.0], netprofit_margin=[35.0, 30.0],
            debt_to_assets=[78.0, 77.0],
        )
        with patch.object(
            fetcher, "_call_api_with_rate_limit", side_effect=lambda name, **kw: calls.append(1) or df
        ):
            fetcher.get_fina_indicator("000783", n=4)
            fetcher.get_fina_indicator("000783", n=4)
            fetcher.get_fina_indicator("000783", n=8)  # 不同 n 不同 key
        assert len(calls) == 2

    def test_failed_fetch_not_cached(self, fetcher):
        calls = []
        with patch.object(
            fetcher, "_call_api_with_rate_limit",
            side_effect=lambda name, **kw: calls.append(1) or pd.DataFrame(),
        ):
            r1 = fetcher.get_forecast("000783")  # 空 df → None，不缓存
            r2 = fetcher.get_forecast("000783")
        assert r1 is None and r2 is None
        assert len(calls) == 2  # None 不进缓存，每次都重拉

    def test_ttl_expiry_refetches(self, fetcher):
        calls = []
        df = _fake_df(
            ts_code=["000783.SZ"], trade_date=["20260818"],
            pe=[13.5], pb=[1.3], total_mv=[5e10], circ_mv=[4e10],
        )
        with patch.object(
            fetcher, "_call_api_with_rate_limit", side_effect=lambda name, **kw: calls.append(1) or df
        ):
            fetcher.get_daily_basic_valuation("000783")
            # 手动把缓存时间戳拨到过期
            key = next(iter(fetcher._fina_cache))
            expire_ts, payload = fetcher._fina_cache[key]
            fetcher._fina_cache[key] = (0.0, payload)
            fetcher.get_daily_basic_valuation("000783")
        assert len(calls) == 2

    def test_cache_eviction_guard(self, fetcher):
        # 容量护栏：超限时先清过期项
        fetcher._fina_cache = {f"k{i}": (0.0, None) for i in range(600)}
        fetcher._fina_cache_put("new_key", "v", ttl=3600)
        assert len(fetcher._fina_cache) == 1
        assert fetcher._fina_cache_get("new_key") == "v"

    def test_cache_hard_cap_when_all_fresh(self, fetcher):
        # 容量护栏硬上限：条目全部在 TTL 内（screener 扫全市场场景）也必须封顶
        fetcher._fina_cache = {f"k{i}": (1e18, None) for i in range(600)}
        fetcher._fina_cache_put("new_key", "v", ttl=3600)
        assert len(fetcher._fina_cache) == fetcher._FINA_CACHE_MAX_ENTRIES
        assert fetcher._fina_cache_get("new_key") == "v"


class TestSharedRateLimit:
    """类级共享限频：多实例共用一个预算。"""

    def test_counter_shared_across_instances(self, fetcher):
        TushareFetcher._shared_call_count = 0
        TushareFetcher._shared_minute_start = None
        with patch.object(TushareFetcher, "_init_api", lambda self: None), \
             patch.object(TushareFetcher, "_determine_priority", lambda self: 2):
            other = TushareFetcher()
        fetcher._check_rate_limit()
        other._check_rate_limit()
        assert TushareFetcher._shared_call_count == 2

    def test_rate_limit_sleeps_when_exceeded(self, fetcher):
        import data_provider.tushare_fetcher as mod
        TushareFetcher._shared_call_count = 80
        TushareFetcher._shared_minute_start = 999.0  # 假时钟 1000 的 1 秒前
        slept = []
        clock = {"now": 1000.0}

        def fake_time():
            return clock["now"]

        def fake_sleep(s):
            clock["now"] += s
            slept.append(s)

        # 假时钟驱动等待+重试，避免真实忙等 ~60s（sleep 被 mock 而 time 为真时的副作用）
        with patch.object(mod.time, "time", fake_time), \
             patch.object(mod.time, "sleep", fake_sleep):
            with patch.object(TushareFetcher, "_init_api", lambda self: None), \
                 patch.object(TushareFetcher, "_determine_priority", lambda self: 2):
                other = TushareFetcher(rate_limit_per_minute=80)
            other._check_rate_limit()  # 第 81 次 → 等待到下一分钟后重试成功
        assert slept == [60.0]  # 60 - 1s elapsed + 1s buffer
        assert TushareFetcher._shared_call_count == 1  # 新窗口重新计数
