"""Tests for BaoStock downloader and DuckDB query layer."""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from src.quant_data.baostock_downloader import BaostockDownloader
from src.quant_data.duckdb_query import QuantQuery
from src.quant_data.config import QuantDataConfig


class TestBaostockDownloader:
    def test_split_into_years(self):
        ranges = BaostockDownloader._split_into_years("2020-01-01", "2023-06-15")
        assert len(ranges) == 4
        assert ranges[0] == ("2020-01-01", "2020-12-31")
        assert ranges[1] == ("2021-01-01", "2021-12-31")
        assert ranges[2] == ("2022-01-01", "2022-12-31")
        assert ranges[3] == ("2023-01-01", "2023-06-15")

    def test_split_single_year(self):
        ranges = BaostockDownloader._split_into_years("2024-03-01", "2024-06-30")
        assert len(ranges) == 1
        assert ranges[0] == ("2024-03-01", "2024-06-30")

    def test_normalize_kline(self, tmp_path):
        config = QuantDataConfig(quant_data_dir=str(tmp_path))
        dl = BaostockDownloader(config)
        raw = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-02"],
            "time": ["093000", "093500"],
            "open": ["60.01", "60.50"],
            "high": ["60.50", "61.00"],
            "low": ["59.80", "60.20"],
            "close": ["60.30", "60.80"],
            "volume": ["100000", "150000"],
            "amount": ["6030000.0", "9120000.0"],
            "adjustflag": ["3", "3"],
        })
        result = dl._normalize_kline(raw, "600519.SS")
        assert len(result) == 2
        assert "datetime" in result.columns
        assert "pct_chg" in result.columns
        assert result["close"].dtype == np.float32
        assert result["volume"].dtype == np.int64


class TestDuckDBQuery:
    def test_query_kline_daily(self):
        """Test against real imported data."""
        with QuantQuery() as q:
            df = q.kline_daily("600519.SS", start_date="2025-01-01", end_date="2025-12-31")
            assert len(df) > 0
            assert "close" in df.columns

    def test_query_valuation(self):
        with QuantQuery() as q:
            df = q.valuation("600519.SS", start_date="2026-01-01")
            assert len(df) > 0
            assert "pe_ttm" in df.columns

    def test_execute_raw_sql(self):
        with QuantQuery() as q:
            df = q.execute("SELECT COUNT(*) as cnt FROM metadata_stock_metadata")
            assert df["cnt"].iloc[0] > 5000

    def test_trade_days(self):
        with QuantQuery() as q:
            df = q.trade_days()
            assert len(df) > 8000
