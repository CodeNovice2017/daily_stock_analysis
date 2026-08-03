"""Tests for quant data storage layer."""
import pytest
import pandas as pd
import numpy as np

from src.quant_data.parquet_store import ParquetStore
from src.quant_data.meta_store import MetaStore
from src.quant_data.progress import ProgressTracker
from src.quant_data.config import QuantDataConfig
from datetime import date


@pytest.fixture
def config(tmp_path):
    return QuantDataConfig(quant_data_dir=str(tmp_path / "quant"))


@pytest.fixture
def store(config):
    return ParquetStore(config)


@pytest.fixture
def meta(config):
    ms = MetaStore(config)
    yield ms
    ms.close()


@pytest.fixture
def progress(tmp_path):
    return ProgressTracker(str(tmp_path / "progress"))


class TestParquetStore:
    def test_write_and_read_daily_partition(self, store):
        df = pd.DataFrame({
            "ts_code": ["600519.SH"] * 3,
            "close": [1800.0, 1810.0, 1820.0],
        })
        store.write_daily_partition("moneyflow", "20260530", df)
        assert store.partition_exists("moneyflow", trade_date="20260530")

        result = store.read_partition("moneyflow", trade_date="20260530")
        assert len(result) == 3
        assert result["close"].tolist() == [1800.0, 1810.0, 1820.0]

    def test_write_and_read_kline_partition(self, store):
        df = pd.DataFrame({
            "datetime": pd.date_range("2024-01-01 09:30", periods=48, freq="5min"),
            "close": np.random.randn(48) + 60.0,
            "volume": np.random.randint(1000, 5000, 48),
        })
        store.write_kline_partition("kline_5min", "600519.SH", 2024, df)
        assert store.partition_exists("kline_5min", symbol="600519.SH", year=2024)

        result = store.read_partition("kline_5min", symbol="600519.SH", year=2024)
        assert len(result) == 48

    def test_kline_partition_merges_on_rewrite(self, store):
        df1 = pd.DataFrame({"close": [60.0], "volume": [100]})
        df2 = pd.DataFrame({"close": [61.0], "volume": [200]})

        store.write_kline_partition("kline_5min", "600519.SH", 2024, df1)
        store.write_kline_partition("kline_5min", "600519.SH", 2024, df2)

        result = store.read_partition("kline_5min", symbol="600519.SH", year=2024)
        assert len(result) == 2

    def test_get_latest_date(self, store):
        df = pd.DataFrame({"x": [1]})
        store.write_daily_partition("test_ds", "20260101", df)
        store.write_daily_partition("test_ds", "20260102", df)
        store.write_daily_partition("test_ds", "20260103", df)
        assert store.get_latest_date("test_ds") == "20260103"

    def test_get_dataset_stats(self, store):
        df = pd.DataFrame({"x": range(100)})
        store.write_daily_partition("stats_test", "20260101", df)
        stats = store.get_dataset_stats("stats_test")
        assert stats["exists"]
        assert stats["rows"] == 100
        assert stats["files"] == 1

    def test_partition_not_exists(self, store):
        assert not store.partition_exists("nonexistent", trade_date="20260101")


class TestMetaStore:
    def test_get_last_date_empty(self, meta):
        assert meta.get_last_date("moneyflow") is None

    def test_update_and_get_last_date(self, meta):
        meta.update_last_date("moneyflow", date(2026, 5, 30))
        assert meta.get_last_date("moneyflow") == date(2026, 5, 30)

    def test_update_advances_watermark(self, meta):
        meta.update_last_date("moneyflow", date(2026, 5, 28))
        meta.update_last_date("moneyflow", date(2026, 5, 30))
        assert meta.get_last_date("moneyflow") == date(2026, 5, 30)

    def test_trade_calendar(self, meta):
        dates = [date(2026, 5, 25), date(2026, 5, 26), date(2026, 5, 27)]
        meta.load_trade_cal(dates)
        result = meta.get_trading_days(date(2026, 5, 25), date(2026, 5, 27))
        assert len(result) == 3


class TestProgressTracker:
    def test_mark_and_check_completed(self, progress):
        assert not progress.is_completed("job1", "600519.SH", 2024)
        progress.mark_completed("job1", "600519.SH", 2024, 12000)
        assert progress.is_completed("job1", "600519.SH", 2024)

    def test_mark_failed(self, progress):
        progress.mark_failed("job1", "600519.SH", 2024, "timeout")
        failed = progress.get_failed("job1")
        assert "600519.SH:2024" in failed

    def test_get_resume_point(self, progress):
        assert progress.get_resume_point("job1", "600519.SH") is None
        progress.mark_completed("job1", "600519.SH", 2023, 12000)
        progress.mark_completed("job1", "600519.SH", 2024, 11000)
        assert progress.get_resume_point("job1", "600519.SH") == "2024"

    def test_reset(self, progress):
        progress.mark_completed("job1", "600519.SH", 2024, 100)
        progress.reset("job1")
        assert not progress.is_completed("job1", "600519.SH", 2024)
