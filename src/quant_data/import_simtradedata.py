from __future__ import annotations

import json
import logging
import tarfile
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.quant_data.config import get_quant_config, QuantDataConfig
from src.quant_data.parquet_store import ParquetStore

logger = logging.getLogger(__name__)


class SimTradeDataImporter:
    """Import SimTradeData archive into our Parquet data lake.

    The archive structure (per-stock daily data):
        stocks/{SYMBOL}.parquet      -> kline_daily (OHLCV + limits)
        valuation/{SYMBOL}.parquet   -> valuation (PE/PB/PS/ROE/market_cap)
        fundamentals/{SYMBOL}.parquet -> fundamentals (quarterly financials)
        exrights/{SYMBOL}.parquet    -> exrights (dividends, splits, adj factors)
        metadata/stock_metadata.parquet -> stock_metadata
        metadata/trade_days.parquet     -> trade_days
        metadata/benchmark.parquet      -> benchmark

    We convert per-stock files into Hive-partitioned format:
        kline_daily/symbol=600519.SS/data.parquet
        valuation/symbol=600519.SS/data.parquet
        ...
    """

    DATASETS = {
        "stocks": "kline_daily",
        "valuation": "valuation",
        "fundamentals": "fundamentals",
        "exrights": "exrights",
    }

    def __init__(self, config: Optional[QuantDataConfig] = None) -> None:
        self._config = config or get_quant_config()
        self._store = ParquetStore(self._config)

    def import_archive(self, archive_path: str) -> dict:
        """Import a SimTradeData .tar.gz archive into our Parquet data lake."""
        archive = Path(archive_path)
        if not archive.exists():
            raise FileNotFoundError(f"Archive not found: {archive}")

        stats = {}
        with tarfile.open(archive, "r:gz") as tar:
            manifest = self._read_manifest(tar)
            logger.info("Archive: %s (%s, %d stocks)",
                        manifest.get("version", "?"),
                        manifest.get("description", "?"),
                        manifest.get("description", "?").split()[0] if manifest else 0)

            for src_dir, dst_dataset in self.DATASETS.items():
                count = self._import_per_stock_dataset(tar, src_dir, dst_dataset)
                stats[dst_dataset] = count
                logger.info("Imported %s: %d stocks", dst_dataset, count)

            # Import metadata files as full tables
            for meta_file in ["stock_metadata", "trade_days", "benchmark"]:
                count = self._import_metadata(tar, meta_file)
                if count is not None:
                    stats[meta_file] = count
                    logger.info("Imported metadata/%s: %d rows", meta_file, count)

        return stats

    def _read_manifest(self, tar: tarfile.TarFile) -> dict:
        try:
            member = tar.getmember("./manifest.json")
            f = tar.extractfile(member)
            if f:
                return json.loads(f.read().decode())
        except KeyError:
            pass
        return {}

    def _import_per_stock_dataset(self, tar: tarfile.TarFile,
                                  src_dir: str, dst_dataset: str) -> int:
        members = [m for m in tar.getmembers()
                   if m.name.startswith(f"./{src_dir}/") and m.name.endswith(".parquet")]
        if not members:
            logger.warning("No files found for %s", src_dir)
            return 0

        count = 0
        for member in members:
            symbol = Path(member.name).stem  # e.g. "600519.SS"
            f = tar.extractfile(member)
            if f is None:
                continue
            try:
                df = pq.read_table(pa.BufferReader(f.read())).to_pandas()
                if df.empty:
                    continue
                df["symbol"] = symbol
                self._store.write_full_table(
                    f"{dst_dataset}/symbol={symbol}",
                    df,
                )
                count += 1
            except Exception as e:
                logger.warning("Failed to import %s: %s", member.name, e)
        return count

    def _import_metadata(self, tar: tarfile.TarFile, name: str) -> Optional[int]:
        member_name = f"./metadata/{name}.parquet"
        try:
            member = tar.getmember(member_name)
        except KeyError:
            return None
        f = tar.extractfile(member)
        if f is None:
            return None
        df = pq.read_table(pa.BufferReader(f.read())).to_pandas()
        if df.empty:
            return 0
        self._store.write_full_table(f"metadata/{name}", df)
        return len(df)
