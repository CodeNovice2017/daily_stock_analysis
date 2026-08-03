from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from src.config import parse_env_float, parse_env_int

_instance: Optional[QuantDataConfig] = None


@dataclass(frozen=True)
class QuantDataConfig:
    quant_data_dir: str = "./data/quant"

    # BaoStock
    quant_bs_start_date: str = "2020-01-01"
    quant_bs_frequency: str = "5"
    quant_bs_batch_size: int = 50
    quant_bs_sleep_between: float = 0.5
    quant_bs_max_workers: int = 4

    # Tushare
    quant_tushare_interfaces: str = "moneyflow,daily_basic"
    quant_tushare_rate_limit: int = 400

    # Parquet
    quant_parquet_compression: str = "zstd"
    quant_parquet_row_group_size: int = 100_000

    # DuckDB
    quant_duckdb_memory_limit: str = "2GB"


def get_quant_config() -> QuantDataConfig:
    global _instance
    if _instance is not None:
        return _instance
    cfg = QuantDataConfig(
        quant_data_dir=os.getenv("QUANT_DATA_DIR", "./data/quant"),
        quant_bs_start_date=os.getenv("QUANT_BS_START_DATE", "2020-01-01"),
        quant_bs_frequency=os.getenv("QUANT_BS_FREQUENCY", "5"),
        quant_bs_batch_size=parse_env_int(
            os.getenv("QUANT_BS_BATCH_SIZE"), 50, field_name="batch_size",
        ),
        quant_bs_sleep_between=parse_env_float(
            os.getenv("QUANT_BS_SLEEP_BETWEEN"), 0.5, field_name="sleep_between",
        ),
        quant_bs_max_workers=parse_env_int(
            os.getenv("QUANT_BS_MAX_WORKERS"), 4, field_name="max_workers", minimum=1, maximum=16,
        ),
        quant_tushare_interfaces=os.getenv("QUANT_TUSHARE_INTERFACES", "moneyflow,daily_basic"),
        quant_tushare_rate_limit=parse_env_int(
            os.getenv("QUANT_TUSHARE_RATE_LIMIT"), 400, field_name="rate_limit",
        ),
        quant_parquet_compression=os.getenv("QUANT_PARQUET_COMPRESSION", "zstd"),
        quant_parquet_row_group_size=parse_env_int(
            os.getenv("QUANT_PARQUET_ROW_GROUP_SIZE"), 100_000, field_name="row_group_size",
        ),
        quant_duckdb_memory_limit=os.getenv("QUANT_DUCKDB_MEMORY_LIMIT", "2GB"),
    )
    _instance = cfg
    return cfg
