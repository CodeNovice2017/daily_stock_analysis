from __future__ import annotations

import logging
from typing import Any, Dict

from src.intraday.types import SignalLevel, SignalResult

logger = logging.getLogger(__name__)

LEVEL_EMOJI = {
    SignalLevel.STRONG: "🔴",
    SignalLevel.MEDIUM: "🟡",
    SignalLevel.WEAK: "🟢",
}


def format_signal_message(
    result: SignalResult,
    stock_name: str = "",
    simulation: bool = False,
) -> str:
    emoji = LEVEL_EMOJI.get(result.level, "⚪")
    time_str = result.triggered_at.strftime("%H:%M")
    lines = [
        f"{emoji} {result.level.name} - {stock_name or result.ts_code} ({result.ts_code})",
        "─" * 24,
        f"信号：{result.signal_name}",
        f"时间：{time_str}",
        f"价格：{result.price:.2f}",
    ]
    for key, val in result.data.items():
        if isinstance(val, float):
            lines.append(f"{key}: {val:.2f}")
        else:
            lines.append(f"{key}: {val}")
    if simulation:
        lines.append("─" * 24)
        lines.append("⚡ 模拟盘模式 — 仅供参考，不构成投资建议")
    return "\n".join(lines)


def format_daily_summary(stats: Dict[str, Any]) -> str:
    trade_date = stats.get("trade_date", "unknown")
    total = stats.get("total_signals", 0)
    lines = [
        f"📊 盘中信号日报 — {trade_date}",
        "─" * 24,
        f"总信号数：{total}",
    ]
    by_signal = stats.get("by_signal", {})
    if by_signal:
        lines.append("")
        lines.append("按信号类型：")
        for name, count in sorted(by_signal.items(), key=lambda x: -x[1]):
            lines.append(f"  {name}: {count}")
    by_code = stats.get("by_ts_code", {})
    if by_code:
        lines.append("")
        lines.append("按股票：")
        for code, count in sorted(by_code.items(), key=lambda x: -x[1]):
            lines.append(f"  {code}: {count}")
    return "\n".join(lines)


class IntradayNotifier:
    """Dispatches intraday signal notifications via NotificationService."""

    def __init__(self, notification_service=None, simulation: bool = True) -> None:
        self._ns = notification_service
        self._simulation = simulation

    def _get_ns(self):
        if self._ns is not None:
            return self._ns
        from src.notification import NotificationService
        return NotificationService()

    def notify(self, result: SignalResult, stock_name: str = "") -> None:
        if result.level < SignalLevel.STRONG:
            return
        msg = format_signal_message(result, stock_name=stock_name, simulation=self._simulation)
        try:
            self._get_ns().send_with_results(msg, route_type="alert")
            logger.info("Sent notification for %s on %s", result.signal_name, result.ts_code)
        except Exception:
            logger.exception("Failed to send notification for %s", result.signal_name)

    def send_daily_summary(self, stats: Dict[str, Any]) -> None:
        msg = format_daily_summary(stats)
        try:
            self._get_ns().send_with_results(msg, route_type="report")
            logger.info("Sent daily summary for %s", stats.get("trade_date"))
        except Exception:
            logger.exception("Failed to send daily summary")
