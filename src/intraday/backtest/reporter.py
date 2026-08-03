from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class BacktestReporter:
    """Aggregates backtest trigger records into per-signal win rate statistics."""

    def __init__(self, win_threshold: float = 0.0) -> None:
        self.win_threshold = win_threshold

    def generate(self, records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        if not records:
            return {}

        grouped: Dict[str, List[Dict]] = {}
        for rec in records:
            name = rec["signal_name"]
            grouped.setdefault(name, []).append(rec)

        report: Dict[str, Dict[str, Any]] = {}
        for name, recs in grouped.items():
            count = len(recs)
            forward_bars = sorted(recs[0]["forward_returns"].keys())
            stats: Dict[str, Any] = {"count": count}
            for fb in forward_bars:
                returns = [r["forward_returns"].get(fb) for r in recs if fb in r.get("forward_returns", {})]
                if not returns:
                    continue
                wins = [r for r in returns if r > self.win_threshold]
                stats[f"win_rate_{fb}"] = round(len(wins) / len(returns), 4)
                stats[f"avg_return_{fb}"] = round(sum(returns) / len(returns), 4)
                stats[f"max_return_{fb}"] = round(max(returns), 4)
                stats[f"min_return_{fb}"] = round(min(returns), 4)
            report[name] = stats
        return report
