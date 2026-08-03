from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import duckdb
import pandas as pd

from src.quant_data.config import get_quant_config, QuantDataConfig

logger = logging.getLogger(__name__)


class QuantQuery:
    """DuckDB SQL query interface over Parquet data lake.

    Borrowed from zer0share: glob-based read_parquet with hive_partitioning.
    """

    def __init__(self, config: Optional[QuantDataConfig] = None) -> None:
        self._config = config or get_quant_config()
        self._root = Path(self._config.quant_data_dir)
        self._con: Optional[duckdb.DuckDBPyConnection] = None
        self._views_registered = False

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            self._con = duckdb.connect(":memory:")
            self._con.execute(f"SET memory_limit='{self._config.quant_duckdb_memory_limit}'")
        if not self._views_registered:
            self.register_views()
            self._views_registered = True
        return self._con

    def register_views(self) -> None:
        """Scan data/quant/ and create DuckDB views for each dataset."""
        if not self._root.exists():
            logger.warning("Data directory %s does not exist", self._root)
            return
        conn = self._con or duckdb.connect(":memory:")
        for dataset_dir in sorted(self._root.iterdir()):
            if not dataset_dir.is_dir() or dataset_dir.name.startswith("_"):
                continue
            name = dataset_dir.name.replace(".", "_").replace("-", "_")

            # Find direct parquet files (not in subdirectories)
            direct_parquets = [f for f in dataset_dir.iterdir() if f.suffix == ".parquet"]
            # Find immediate subdirectories with parquet files
            sub_dirs_with_data = [
                d for d in dataset_dir.iterdir()
                if d.is_dir() and list(d.glob("*.parquet"))
            ]

            if direct_parquets:
                # Single-file dataset at this level
                self._create_view(conn, name, direct_parquets[0])
                continue

            if not sub_dirs_with_data:
                continue

            # Check if this is a per-symbol dataset (has symbol= dirs)
            symbol_dirs = list(dataset_dir.glob("symbol=*"))
            if symbol_dirs:
                for sym_dir in sorted(symbol_dirs):
                    sym_name = sym_dir.name.replace(".", "_")
                    sub_dirs = [d for d in sym_dir.iterdir() if d.is_dir()]
                    if sub_dirs:
                        for sub in sorted(sub_dirs):
                            pq_path = sub / "data.parquet"
                            if pq_path.exists():
                                view_name = f"{name}_{sym_name}_{sub.name}"
                                self._create_view(conn, view_name, pq_path)
                    else:
                        pq_path = sym_dir / "data.parquet"
                        if pq_path.exists():
                            view_name = f"{name}_{sym_name}"
                            self._create_view(conn, view_name, pq_path)
                self._create_union_view(conn, name, dataset_dir)
            else:
                # Each subdirectory is its own dataset (e.g. metadata/stock_metadata)
                for sub in sorted(sub_dirs_with_data):
                    pq_files = list(sub.glob("*.parquet"))
                    if len(pq_files) == 1:
                        self._create_view(conn, f"{name}_{sub.name}", pq_files[0])
                    else:
                        self._create_union_view(conn, f"{name}_{sub.name}", sub)

    def _create_view(self, conn: duckdb.DuckDBPyConnection,
                     name: str, path: Path) -> None:
        safe_name = name.replace("=", "_")
        conn.execute(
            f"CREATE OR REPLACE VIEW \"{safe_name}\" AS "
            f"SELECT * FROM read_parquet('{path}')"
        )
        logger.debug("Created view %s -> %s", safe_name, path)

    def _create_union_view(self, conn: duckdb.DuckDBPyConnection,
                           name: str, dataset_dir: Path) -> None:
        """Create a union view across all parquet files in a dataset."""
        pattern = str(dataset_dir / "**" / "*.parquet")
        conn.execute(
            f"CREATE OR REPLACE VIEW \"{name}\" AS "
            f"SELECT * FROM read_parquet('{pattern}', hive_partitioning=true, "
            f"union_by_name=true, filename=true)"
        )
        logger.debug("Created union view %s -> %s/**", name, dataset_dir)

    def execute(self, sql: str) -> pd.DataFrame:
        """Execute arbitrary SQL and return DataFrame."""
        conn = self._get_conn()
        return conn.execute(sql).fetchdf()

    def kline_daily(self, symbol: str, start_date: Optional[str] = None,
                    end_date: Optional[str] = None) -> pd.DataFrame:
        """Load daily K-line for a single stock."""
        sym_view = f"kline_daily_symbol_{symbol.replace('.', '_')}"
        sql = f'SELECT * FROM "{sym_view}"'
        wheres = []
        if start_date:
            wheres.append(f"date >= '{start_date}'")
        if end_date:
            wheres.append(f"date <= '{end_date}'")
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY date"
        return self.execute(sql)

    def valuation(self, symbol: str, start_date: Optional[str] = None,
                  end_date: Optional[str] = None) -> pd.DataFrame:
        """Load valuation data for a single stock."""
        sym_view = f"valuation_symbol_{symbol.replace('.', '_')}"
        sql = f'SELECT * FROM "{sym_view}"'
        wheres = []
        if start_date:
            wheres.append(f"date >= '{start_date}'")
        if end_date:
            wheres.append(f"date <= '{end_date}'")
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY date"
        return self.execute(sql)

    def stock_metadata(self) -> pd.DataFrame:
        """Load stock metadata."""
        return self.execute("SELECT * FROM metadata_stock_metadata")

    def trade_days(self) -> pd.DataFrame:
        """Load trade calendar."""
        return self.execute("SELECT * FROM metadata_trade_days")

    def close(self) -> None:
        if self._con:
            self._con.close()
            self._con = None

    def __enter__(self) -> QuantQuery:
        return self

    def __exit__(self, *args) -> None:
        self.close()
