# -*- coding: utf-8 -*-
"""run_outcome_backfill._backfill_daily_bars 的收盘保护与容错测试。

覆盖三个风险点：
1. 15:30（沪）前拉到的当日 bar 必须丢弃——盘中半根 K 落库会被评估
   采用，把信号错误定案为 completed（completed 不会重算，属永久污染）。
2. 单只代码拉取失败只计数告警，不阻断其余代码与后续评估。
3. 代码集合仅取近 30 天有信号/样本的股票，历史代码不再无限拉取。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from scripts.run_outcome_backfill import _backfill_daily_bars

_CN = ZoneInfo("Asia/Shanghai")


class _FakeProvider:
    """返回 [前一日, 当日] 两根 bar；FAIL 代码抛错。"""

    calls: list = []

    def __init__(self):
        pass

    def get_daily_data(self, code: str, days: int = 180):
        type(self).calls.append(code)
        if code == "000BAD":
            raise RuntimeError("boom")
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-09-01", "2026-09-02"]),
                "open": [1.0, 1.1],
                "high": [1.2, 1.3],
                "low": [0.9, 1.0],
                "close": [1.1, 1.2],
                "volume": [100, 200],
            }
        )


class _FakeDB:
    def __init__(self):
        self.saved: list = []

    def save_daily_data(self, df, code, data_source="Unknown", canonical_id=None):
        self.saved.append((code, sorted(d.date() for d in df["date"]), data_source))
        return len(df)


def _make_signal_db(path):
    conn = sqlite3.connect(path)
    conn.execute("create table decision_signals (stock_code text, created_at text)")
    conn.execute("create table skill_opinion_samples (stock_code text, created_at text)")
    # 近 30 天：三个代码（含仅出现在 skill 样本表的一个）
    conn.execute(
        "insert into decision_signals values ('600900', '2026-08-25 08:00:00')"
    )
    conn.execute("insert into decision_signals values ('000BAD', '2026-08-26 08:00:00')")
    conn.execute(
        "insert into skill_opinion_samples values ('512880', '2026-08-27 08:00:00')"
    )
    # 超出 30 天回看窗的旧代码，不应被拉取
    conn.execute(
        "insert into decision_signals values ('600000', '2026-01-01 08:00:00')"
    )
    conn.commit()
    conn.close()


def _patch_deps(monkeypatch, tmp_path):
    db_path = str(tmp_path / "signals.db")
    _make_signal_db(db_path)
    fake_db = _FakeDB()
    _FakeProvider.calls = []
    monkeypatch.setattr("src.config.get_config", lambda: SimpleNamespace(database_path=db_path))
    monkeypatch.setattr("src.ml_agent.screener.data_provider.MLDataProvider", _FakeProvider)
    monkeypatch.setattr("src.storage.get_db", lambda: fake_db)
    return fake_db


def test_backfill_daily_bars_drops_today_before_close(monkeypatch, tmp_path):
    """15:30 前丢弃当日行，仅落库前一日的完整 bar。"""
    fake_db = _patch_deps(monkeypatch, tmp_path)
    fail = _backfill_daily_bars(now=datetime(2026, 9, 2, 9, 30, tzinfo=_CN))

    assert fail == 1  # 000BAD 拉取失败
    assert set(_FakeProvider.calls) == {"600900", "000BAD", "512880"}  # 旧代码不拉
    by_code = {code: dates for code, dates, _ in fake_db.saved}
    assert set(by_code) == {"600900", "512880"}
    for dates in by_code.values():
        assert dates == [datetime(2026, 9, 1).date()]


def test_backfill_daily_bars_keeps_today_after_close(monkeypatch, tmp_path):
    """15:30 后（含边界 15:30 整）保留当日完整 bar，判分需要当日收盘。"""
    fake_db = _patch_deps(monkeypatch, tmp_path)
    _backfill_daily_bars(now=datetime(2026, 9, 2, 15, 30, tzinfo=_CN))

    by_code = {code: dates for code, dates, _ in fake_db.saved}
    for dates in by_code.values():
        assert dates == [datetime(2026, 9, 1).date(), datetime(2026, 9, 2).date()]


def test_backfill_daily_bars_no_recent_codes_skips(monkeypatch, tmp_path):
    """无近期信号时不初始化数据源，直接返回 0。"""
    db_path = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db_path)
    conn.execute("create table decision_signals (stock_code text, created_at text)")
    conn.execute("create table skill_opinion_samples (stock_code text, created_at text)")
    conn.commit()
    conn.close()

    def _boom():
        raise AssertionError("不应初始化数据源")

    monkeypatch.setattr("src.config.get_config", lambda: SimpleNamespace(database_path=db_path))
    monkeypatch.setattr("src.ml_agent.screener.data_provider.MLDataProvider", _boom)
    monkeypatch.setattr("src.storage.get_db", _boom)

    assert _backfill_daily_bars(now=datetime(2026, 9, 2, 16, 0, tzinfo=_CN)) == 0
