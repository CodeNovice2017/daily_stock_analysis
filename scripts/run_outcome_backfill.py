#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[personal patch] P1-C：决策信号 + Skill 观点的复盘回填入口。

用途：收盘后增量评估历史判断的方向对错（hit/miss/neutral），
供 cc-connect cron / 手动 / CI 定期执行。幂等：已评估的不重复计算。

评估依赖本地 stock_daily 落库；未被当日分析命中的信号股不会写入当日
bar，导致 insufficient_forward_bars / missing_anchor_price 反复出现。
评估前会先对近期信号股自动回补 K 线（Tushare 直连，见
``_backfill_daily_bars``），15:30（沪）前丢弃当日 bar 防止半根 K 线
污染判分（completed 结果不会重算）。

用法：
    .venv/bin/python scripts/run_outcome_backfill.py            # 增量（含 K 线回补）
    .venv/bin/python scripts/run_outcome_backfill.py --stats    # 只看统计不评估
    .venv/bin/python scripts/run_outcome_backfill.py --skip-bars  # 跳过 K 线回补（调试）
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _backfill_daily_bars(
    *,
    signal_lookback_days: int = 30,
    fetch_days: int = 12,
    now=None,
) -> int:
    """评估前对近期信号股自动回补日线，返回失败代码数。

    - 代码来源：近 ``signal_lookback_days`` 天有 decision_signals 或
      skill_opinion_samples 记录的股票（判分最多看 10 个交易日前瞻，
      30 天余量足够；同时避免随历史信号增长无限拉取）。
    - 收盘保护：沪市 15:00 收盘，留 30 分钟数据落地缓冲；15:30 前拉到的
      当日 bar 是半根，落库后被评估采用会把信号错误定案为 completed
      （completed 不会重算），故一律丢弃当日行。港股 16:00 收盘，
      当前信号全为 A 股，若未来出现港股信号需按市场细化此过滤。
    - 回补失败不阻断评估：打印告警后继续，已落库数据仍可评估。
    - ``now``：注入当前时间（含 tzinfo，沪区），测试用；缺省取系统时间。
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    import pandas as pd

    from src.config import get_config
    from src.ml_agent.screener.data_provider import MLDataProvider
    from src.storage import get_db

    cn_now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    keep_today = cn_now.hour > 15 or (cn_now.hour == 15 and cn_now.minute >= 30)
    today = cn_now.date()

    cutoff = (cn_now - timedelta(days=signal_lookback_days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(get_config().database_path)
    try:
        codes = {
            row[0]
            for row in conn.execute(
                "select distinct stock_code from decision_signals where created_at >= ?",
                (cutoff,),
            )
        }
        codes |= {
            row[0]
            for row in conn.execute(
                "select distinct stock_code from skill_opinion_samples where created_at >= ?",
                (cutoff,),
            )
        }
    finally:
        conn.close()

    if not codes:
        print("[bars] 近期无信号股票，跳过 K 线回补")
        return 0

    try:
        provider = MLDataProvider()
    except Exception as exc:  # 无 TUSHARE_TOKEN 等环境缺失：不阻断评估
        print(f"[bars] K 线回补初始化失败，判分继续（缺少自动补数）: {exc}")
        return 0

    db = get_db()
    ok = fail = new_bars = 0
    for code in sorted(codes):
        try:
            df = provider.get_daily_data(code, days=fetch_days)
        except Exception as exc:
            fail += 1
            print(f"[bars] {code} 拉取失败: {exc}")
            continue
        if df is None or df.empty:
            fail += 1
            print(f"[bars] {code} 返回空数据")
            continue
        if not keep_today and "date" in df.columns:
            df = df[pd.to_datetime(df["date"]).dt.date != today]
        if not df.empty:
            try:
                # 注意参数序：save_daily_data(df, code)，传反会报
                # 'str' object has no attribute 'empty'
                new_bars += db.save_daily_data(df, code, data_source="TushareFetcher")
            except Exception as exc:
                fail += 1
                print(f"[bars] {code} 落库失败: {exc}")
                continue
        ok += 1
    print(
        f"[bars] 回补完成: codes={len(codes)} ok={ok} fail={fail} "
        f"new_bars={new_bars} keep_today={keep_today}"
    )
    return fail


def _run_backfill(limit: int = 500) -> int:
    from src.services.decision_signal_outcome_service import DecisionSignalOutcomeService
    from src.services.skill_opinion_outcome_service import SkillOpinionOutcomeService

    ds = DecisionSignalOutcomeService().run_outcomes(limit=limit)
    sk = SkillOpinionOutcomeService().run_outcomes(limit=limit)
    print(
        f"[decision-signals] evaluated={ds.get('evaluated')} "
        f"created={ds.get('created')} updated={ds.get('updated')}"
    )
    print(
        f"[skill-opinions] processed={sk.get('processed_keys')} "
        f"created={sk.get('created')} updated={sk.get('updated')}"
    )
    return 0


def _print_stats() -> int:
    # 注：这里绕过 repository 层直接读 sqlite 做只读统计——查的是 outcomes
    # 聚合而非业务写入，避免为统计脚本引入完整 repo 依赖；若
    # decision_signal_outcomes / skill_opinion_outcomes 表结构变更，需同步此处。
    from src.config import get_config

    conn = sqlite3.connect(get_config().database_path)
    conn.row_factory = sqlite3.Row

    print("== 决策信号判定分布 ==")
    for r in conn.execute(
        "select eval_status, outcome, count(*) c from decision_signal_outcomes group by 1,2 order by c desc"
    ):
        print(f"  {r['eval_status']}/{r['outcome']}: {r['c']}")

    print("== Skill 观点命中分布（按 skill） ==")
    q = (
        "select s.skill_id, o.outcome, count(*) c "
        "from skill_opinion_outcomes o "
        "join skill_opinion_samples s on s.id = o.skill_opinion_sample_id "
        "where o.outcome in ('hit','miss') group by 1,2 order by 1"
    )
    per_skill: Counter = Counter()
    for r in conn.execute(q):
        per_skill[(r["skill_id"], r["outcome"])] = r["c"]
    skills = sorted({k for k, _ in per_skill})
    total_hit = total_miss = 0
    for sk in skills:
        hit, miss = per_skill[(sk, "hit")], per_skill[(sk, "miss")]
        total_hit += hit
        total_miss += miss
        n = hit + miss
        print(f"  {sk}: {hit}/{n} 命中 ({hit * 100 // max(n, 1)}%)")
    n_all = total_hit + total_miss
    if n_all:
        print(f"  合计: {total_hit}/{n_all} 命中 ({total_hit * 100 // n_all}%)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="决策复盘回填/统计")
    parser.add_argument("--stats", action="store_true", help="只打印统计，不执行评估")
    parser.add_argument("--skip-bars", action="store_true", help="跳过 K 线回补，直接评估（调试用）")
    parser.add_argument("--limit", type=int, default=500, help="单次评估上限（默认 500）")
    args = parser.parse_args()
    if args.stats:
        return _print_stats()
    if not args.skip_bars:
        _backfill_daily_bars()
    rc = _run_backfill(args.limit)
    _print_stats()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
