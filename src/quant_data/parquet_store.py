from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd

from src.quant_data.config import get_quant_config, QuantDataConfig

logger = logging.getLogger(__name__)


class ParquetStore:
    """Read/write Parquet files with Hive-style partitioning."""

    def __init__(self, config: Optional[QuantDataConfig] = None) -> None:
        self._config = config or get_quant_config()
        self._root = Path(self._config.quant_data_dir)

    @property
    def root(self) -> Path:
        return self._root

    def write_daily_partition(
        self,
        dataset: str,
        trade_date: str,
        df: pd.DataFrame,
    ) -> str:
        """Write a date-partitioned Parquet file. trade_date in YYYYMMDD format."""
        partition_dir = self._root / dataset / f"date={trade_date}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        path = partition_dir / "data.parquet"
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(
            table,
            path,
            compression=self._config.quant_parquet_compression,
            row_group_size=self._config.quant_parquet_row_group_size,
            use_dictionary=False,
        )
        logger.info("Wrote %s: %d rows to %s", dataset, len(df), path)
        return str(path)

    def write_kline_partition(
        self,
        dataset: str,
        symbol: str,
        year: int,
        df: pd.DataFrame,
    ) -> str:
        """Write a symbol+year partitioned Parquet file. Appends/overwrites."""
        partition_dir = self._root / dataset / f"symbol={symbol}" / f"year={year}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        path = partition_dir / "data.parquet"
        if path.exists():
            existing = pq.ParquetFile(path).read().to_pandas()
            df = pd.concat([existing, df]).drop_duplicates()
        # Disable dictionary encoding to avoid type mismatch on append
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(
            table,
            path,
            compression=self._config.quant_parquet_compression,
            row_group_size=self._config.quant_parquet_row_group_size,
            use_dictionary=False,
        )
        logger.info("Wrote %s/%s/%d: %d rows", dataset, symbol, year, len(df))
        return str(path)

    def write_full_table(self, dataset: str, df: pd.DataFrame) -> str:
        """Write a single-file dataset (e.g. metadata)."""
        path = self._root / dataset
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / "data.parquet"
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(
            table,
            file_path,
            compression=self._config.quant_parquet_compression,
        )
        logger.info("Wrote %s: %d rows", dataset, len(df))
        return str(file_path)

    def partition_exists(self, dataset: str, trade_date: Optional[str] = None,
                         symbol: Optional[str] = None, year: Optional[int] = None) -> bool:
        """Check if a partition file already exists."""
        if trade_date:
            path = self._root / dataset / f"date={trade_date}" / "data.parquet"
        elif symbol and year:
            path = self._root / dataset / f"symbol={symbol}" / f"year={year}" / "data.parquet"
        else:
            return False
        return path.exists()

    def read_partition(self, dataset: str, trade_date: Optional[str] = None,
                       symbol: Optional[str] = None, year: Optional[int] = None) -> pd.DataFrame:
        """Read a specific partition."""
        if trade_date:
            path = self._root / dataset / f"date={trade_date}" / "data.parquet"
        elif symbol and year:
            path = self._root / dataset / f"symbol={symbol}" / f"year={year}" / "data.parquet"
        else:
            return pd.DataFrame()
        if not path.exists():
            return pd.DataFrame()
        return pq.ParquetFile(path).read().to_pandas()

    def get_latest_date(self, dataset: str) -> Optional[str]:
        """Find the latest date in a date-partitioned dataset."""
        dataset_dir = self._root / dataset
        if not dataset_dir.exists():
            return None
        dates = []
        for d in dataset_dir.iterdir():
            if d.is_dir() and d.name.startswith("date="):
                dates.append(d.name[5:])
        return max(dates) if dates else None

    def get_dataset_stats(self, dataset: str) -> Dict[str, Any]:
        """Return total rows and file count for a dataset."""
        dataset_dir = self._root / dataset
        if not dataset_dir.exists():
            return {"dataset": dataset, "exists": False}
        total_rows = 0
        total_size = 0
        file_count = 0
        for pf in dataset_dir.rglob("*.parquet"):
            total_size += pf.stat().st_size
            file_count += 1
            try:
                total_rows += pq.read_metadata(pf).num_rows
            except Exception:
                pass
        return {
            "dataset": dataset,
            "exists": True,
            "files": file_count,
            "rows": total_rows,
            "size_mb": round(total_size / 1024 / 1024, 1),
        }

    def list_datasets(self) -> List[str]:
        """List all dataset directories."""
        if not self._root.exists():
            return []
        return [d.name for d in self._root.iterdir() if d.is_dir() and not d.name.startswith("_")]
