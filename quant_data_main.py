#!/usr/bin/env python3
"""Quantitative data pipeline CLI entry point.

Usage:
    python quant_data_main.py --quant-download-kline [--symbol 600519.SS] [--start-date YYYY-MM-DD] [--resume]
    python quant_data_main.py --quant-pull-daily [--date YYYYMMDD]
    python quant_data_main.py --quant-pull-backfill --interface moneyflow --start-year 2020
    python quant_data_main.py --quant-schedule [--time 18:30]
    python quant_data_main.py --quant-query "SELECT * FROM kline_daily LIMIT 10"
    python quant_data_main.py --quant-status
    python quant_data_main.py --quant-import-archive /path/to/simtradelab-data-cn.tar.gz
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("quant_data_main")


def run_download_kline(args):
    from src.quant_data.baostock_downloader import BaostockDownloader

    dl = BaostockDownloader()
    if args.symbol:
        rows = dl.download_single(args.symbol, args.start_date, args.end_date)
        print(f"Downloaded {rows} bars for {args.symbol}")
    else:
        symbols = args.symbol_list.split(",") if args.symbol_list else None
        results = dl.download_all(
            symbols=symbols,
            start_date=args.start_date,
            end_date=args.end_date,
            resume=args.resume,
        )
        total = sum(results.values())
        print(f"Downloaded {total} bars for {len(results)} stocks")


def run_pull_daily(args):
    from src.quant_data.tushare_downloader import TushareDownloader

    dl = TushareDownloader()
    results = dl.pull_daily_incremental(trade_date=args.date)
    for name, result in results.items():
        print(f"  {name}: {result.status.value} ({result.rows_fetched} rows)")


def run_backfill(args):
    from src.quant_data.tushare_downloader import TushareDownloader

    dl = TushareDownloader()
    total = dl.pull_backfill(args.interface, args.start_year, args.end_year)
    print(f"Backfilled {total} rows for {args.interface}")


def run_schedule(args):
    from src.quant_data.scheduler import QuantDataScheduler

    scheduler = QuantDataScheduler()
    scheduler.run_loop(schedule_time=args.time)


def run_query(args):
    from src.quant_data.duckdb_query import QuantQuery

    with QuantQuery() as q:
        df = q.execute(args.quant_query)
        print(df.to_string(max_rows=50))


def run_status(args):
    from src.quant_data.parquet_store import ParquetStore

    store = ParquetStore()
    for dataset in sorted(store.list_datasets()):
        stats = store.get_dataset_stats(dataset)
        if stats.get("exists"):
            print(f"  {dataset}: {stats['files']} files, {stats['rows']:,} rows, {stats['size_mb']} MB")
        else:
            print(f"  {dataset}: not found")


def run_import_archive(args):
    from src.quant_data.import_simtradedata import SimTradeDataImporter

    importer = SimTradeDataImporter()
    stats = importer.import_archive(args.archive_path)
    print("Import complete:")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")


def main():
    parser = argparse.ArgumentParser(description="Quantitative Data Pipeline")

    parser.add_argument("--quant-download-kline", action="store_true",
                        help="Download minute K-line from BaoStock")
    parser.add_argument("--quant-pull-daily", action="store_true",
                        help="Pull daily incremental data from Tushare")
    parser.add_argument("--quant-pull-backfill", action="store_true",
                        help="Backfill historical Tushare data")
    parser.add_argument("--quant-schedule", action="store_true",
                        help="Start scheduled daily pull")
    parser.add_argument("--quant-query", type=str, default=None,
                        help="Execute SQL query against Parquet data")
    parser.add_argument("--quant-status", action="store_true",
                        help="Show data lake status")
    parser.add_argument("--quant-import-archive", type=str, default=None,
                        help="Import SimTradeData archive (.tar.gz)")

    # Options
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--symbol-list", type=str, default=None,
                        help="Comma-separated symbol list")
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--interface", type=str, default="moneyflow")
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--time", type=str, default="18:30")

    args = parser.parse_args()

    if args.quant_download_kline:
        run_download_kline(args)
    elif args.quant_pull_daily:
        run_pull_daily(args)
    elif args.quant_pull_backfill:
        run_backfill(args)
    elif args.quant_schedule:
        run_schedule(args)
    elif args.quant_query:
        run_query(args)
    elif args.quant_status:
        run_status(args)
    elif args.quant_import_archive:
        args.archive_path = args.quant_import_archive
        run_import_archive(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
