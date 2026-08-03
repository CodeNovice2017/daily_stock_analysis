from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List

import duckdb

from src.quant_data.config import get_quant_config, QuantDataConfig

logger = logging.getLogger(__name__)


class MetaStore:
    """DuckDB-based sync watermark tracker (borrowed from zer0share pattern)."""

    def __init__(self, config: Optional[QuantDataConfig] = None) -> None:
        self._config = config or get_quant_config()
        db_path = Path(self._config.quant_data_dir) / "_meta" / "sync_meta.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_meta (
                table_name  VARCHAR PRIMARY KEY,
                last_date   DATE,
                updated_at  TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_cal (
                exchange      VARCHAR,
                cal_date      DATE,
                is_open       BOOLEAN,
                PRIMARY KEY (exchange, cal_date)
            )
        """)

    def get_last_date(self, table_name: str) -> Optional[date]:
        row = self._conn.execute(
            "SELECT last_date FROM sync_meta WHERE table_name = ?", [table_name],
        ).fetchone()
        return row[0] if row else None

    def update_last_date(self, table_name: str, last_date: date) -> None:
        self._conn.execute(
            """INSERT INTO sync_meta (table_name, last_date, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT (table_name) DO UPDATE SET last_date = ?, updated_at = ?""",
            [table_name, last_date, datetime.now(), last_date, datetime.now()],
        )

    def load_trade_cal(self, dates: List[date]) -> None:
        """Bulk load trade calendar dates."""
        if not dates:
            return
        self._conn.execute("DELETE FROM trade_cal WHERE exchange = 'SSE'")
        for d in dates:
            self._conn.execute(
                "INSERT INTO trade_cal VALUES ('SSE', ?, true)", [d],
            )

    def get_trading_days(self, start: date, end: date) -> List[date]:
        rows = self._conn.execute(
            "SELECT cal_date FROM trade_cal WHERE exchange = 'SSE' AND is_open = true "
            "AND cal_date >= ? AND cal_date <= ? ORDER BY cal_date",
            [start, end],
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> MetaStore:
        return self

    def __exit__(self, *args) -> None:
        self.close()
