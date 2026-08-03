#!/usr/bin/env python3
"""Intraday monitoring system CLI entry point.

Usage:
    python intraday_main.py --intraday-backtest [--signal SIGNAL_NAME]
    python intraday_main.py --intraday-monitor
    python intraday_main.py --intraday-evolve
"""
import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("intraday_main")


def run_backtest(args) -> None:
    from src.intraday.backtest.engine import BacktestEngine
    from src.intraday.backtest.loader import BacktestDataLoader
    from src.intraday.backtest.reporter import BacktestReporter
    from src.config import get_config
    from src.intraday.signals import ALL_SIGNALS
    from src.intraday.types import SignalContext

    config = get_config()
    watch_list = config.intraday_watch_list
    if not watch_list:
        logger.error("INTRADAY_WATCH_LIST is empty. Set it in .env")
        sys.exit(1)

    signal_classes = ALL_SIGNALS
    if args.signal:
        signal_classes = [s for s in ALL_SIGNALS if s().name == args.signal]
        if not signal_classes:
            logger.error("Unknown signal: %s", args.signal)
            sys.exit(1)

    signals = [cls() for cls in signal_classes]
    loader = BacktestDataLoader()
    engine = BacktestEngine(signals=signals)
    reporter = BacktestReporter()

    all_records = []
    for ts_code in watch_list:
        logger.info("Loading data for %s...", ts_code)
        df = loader.load(ts_code, days=config.intraday_backtest_days)
        if df is None:
            logger.warning("Skipping %s — no data", ts_code)
            continue
        ctx = SignalContext(ts_code=ts_code)
        records = engine.run(df, ctx)
        all_records.extend(records)

    report = reporter.generate(all_records)
    print("\n===== Backtest Report =====")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    total = sum(r["count"] for r in report.values())
    print(f"\nTotal triggers: {total}")
    for name, stats in report.items():
        wr6 = stats.get("win_rate_6", "N/A")
        if isinstance(wr6, float):
            wr6 = f"{wr6:.1%}"
        wr12 = stats.get("win_rate_12", "N/A")
        if isinstance(wr12, float):
            wr12 = f"{wr12:.1%}"
        threshold = config.intraday_strong_threshold / 100
        status = "PASS" if stats.get("win_rate_6", 0) >= threshold else "BELOW THRESHOLD"
        print(f"  {name}: {stats['count']} triggers, win_rate_6={wr6}, win_rate_12={wr12} [{status}]")


def run_monitor(args) -> None:
    from src.config import get_config
    from src.intraday.scheduler import IntradayScheduler

    config = get_config()
    watch_list = config.intraday_watch_list
    if not watch_list:
        logger.error("INTRADAY_WATCH_LIST is empty. Set it in .env")
        sys.exit(1)

    scheduler = IntradayScheduler(
        watch_list=watch_list,
        poll_interval_minutes=config.intraday_poll_interval,
        simulation=True,
    )
    logger.info("Starting intraday monitor for %d stocks: %s", len(watch_list), ", ".join(watch_list))
    try:
        scheduler.run_loop()
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")


def run_evolve(args) -> None:
    from datetime import date
    from src.intraday.store import IntradaySignalStore
    from src.intraday.notifier import IntradayNotifier

    store = IntradaySignalStore()
    today = date.today()
    stats = store.get_daily_stats(today)

    if stats["total_signals"] == 0:
        print(f"No signals recorded for {today}")
        return

    print(f"\n===== Daily Review — {today} =====")
    print(f"Total signals: {stats['total_signals']}")
    for name, count in stats.get("by_signal", {}).items():
        print(f"  {name}: {count}")
    for code, count in stats.get("by_ts_code", {}).items():
        print(f"  {code}: {count}")

    notifier = IntradayNotifier(simulation=True)
    notifier.send_daily_summary(stats)
    print("\nDaily summary sent.")


def main():
    parser = argparse.ArgumentParser(description="Intraday Monitoring System")
    parser.add_argument("--intraday-backtest", action="store_true", help="Run signal backtest")
    parser.add_argument("--intraday-monitor", action="store_true", help="Start intraday monitoring")
    parser.add_argument("--intraday-evolve", action="store_true", help="Run daily evolution/review")
    parser.add_argument("--signal", type=str, default=None, help="Specific signal to backtest")
    args = parser.parse_args()

    if args.intraday_backtest:
        run_backtest(args)
    elif args.intraday_monitor:
        run_monitor(args)
    elif args.intraday_evolve:
        run_evolve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
