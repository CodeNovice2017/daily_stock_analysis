# -*- coding: utf-8 -*-
"""涨停余温扫描器 CLI 入口。"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="涨停余温扫描器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--date", type=str, default=None, help="扫描日期 (YYYY-MM-DD)，默认当天")
    parser.add_argument("--no-notify", action="store_true", help="不推送通知")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    parser.add_argument("--status", action="store_true", help="查看当前跟踪状态摘要")
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # 引导上游环境（.env 等）
    try:
        from src.config import setup_env
        setup_env()
    except Exception:
        pass

    from src.stock_screener.service import ScreenerService

    svc = ScreenerService()

    if args.status:
        svc.print_status()
        return 0

    target_date = None
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("无效日期格式: %s (需要 YYYY-MM-DD)", args.date)
            return 1

    stats = svc.run_daily(
        target_date=target_date,
        send_notification=not args.no_notify,
    )
    logger.info(
        "扫描完成: date=%s detected=%d evaluated=%d qualified=%d failed=%d expired=%d errors=%d",
        stats.get("scan_date"),
        stats.get("detected", 0),
        stats.get("evaluated", 0),
        stats.get("qualified", 0),
        stats.get("failed", 0),
        stats.get("expired", 0),
        stats.get("errors", 0),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
