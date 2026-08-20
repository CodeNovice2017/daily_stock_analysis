#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[personal patch] P1-C：决策信号 + Skill 观点的复盘回填入口。

用途：收盘后增量评估历史判断的方向对错（hit/miss/neutral），
供 cc-connect cron / 手动 / CI 定期执行。幂等：已评估的不重复计算。

用法：
    .venv/bin/python scripts/run_outcome_backfill.py            # 增量
    .venv/bin/python scripts/run_outcome_backfill.py --stats    # 只看统计不评估
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
    parser.add_argument("--limit", type=int, default=500, help="单次评估上限（默认 500）")
    args = parser.parse_args()
    if args.stats:
        return _print_stats()
    rc = _run_backfill(args.limit)
    _print_stats()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
