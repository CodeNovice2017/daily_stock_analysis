"""Tests for Tushare downloader (mocked HTTP, no real API calls)."""
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import date

from src.quant_data.tushare_downloader import (
    TushareDownloader,
    MONEYFLOW_COLS,
    DAILY_BASIC_COLS,
    CYQ_CHIPS_COLS,
)
from src.quant_data.config import QuantDataConfig
from src.quant_data.types import DownloadStatus


@pytest.fixture
def config(tmp_path):
    return QuantDataConfig(quant_data_dir=str(tmp_path))


@pytest.fixture
def mock_token():
    with patch("src.quant_data.tushare_downloader.get_main_config") as mock_cfg:
        mock_cfg.return_value.tushare_token = "test_token_123"
        yield mock_cfg


@pytest.fixture
def dl(config, mock_token):
    return TushareDownloader(config)


def _tushare_response(fields, items):
    return {"code": 0, "msg": "", "data": {"fields": fields, "items": items}}


class TestColumnConstants:
    def test_moneyflow_cols(self):
        assert "ts_code" in MONEYFLOW_COLS
        assert "trade_date" in MONEYFLOW_COLS
        assert "net_mf_amount" in MONEYFLOW_COLS

    def test_daily_basic_cols(self):
        assert "pe" in DAILY_BASIC_COLS
        assert "pb" in DAILY_BASIC_COLS
        assert "total_mv" in DAILY_BASIC_COLS

    def test_cyq_chips_cols(self):
        assert "ts_code" in CYQ_CHIPS_COLS
        assert "price" in CYQ_CHIPS_COLS


class TestCallTushare:
    def test_success_returns_dataframe(self, dl):
        payload = _tushare_response(
            ["ts_code", "trade_date", "net_mf_vol"],
            [["000001.SZ", "20240102", "1000"]],
        )
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = payload
            mock_post.return_value.status_code = 200
            df = dl._call_tushare("moneyflow", trade_date="20240102")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert "ts_code" in df.columns

    def test_api_error_returns_empty(self, dl):
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"code": -1, "msg": "error"}
            mock_post.return_value.status_code = 200
            df = dl._call_tushare("moneyflow", trade_date="20240102")

        assert df.empty

    def test_empty_items_returns_empty_df_with_columns(self, dl):
        payload = _tushare_response(["ts_code", "trade_date"], [])
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = payload
            df = dl._call_tushare("moneyflow", trade_date="20240102")

        assert df.empty
        assert list(df.columns) == ["ts_code", "trade_date"]


class TestPullDailyIncremental:
    def test_moneyflow_pull(self, dl):
        items = [["000001.SZ", "20240102"] + ["100"] * 18]
        payload = _tushare_response(MONEYFLOW_COLS, items)
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = payload
            results = dl.pull_daily_incremental(
                trade_date="20240102", interfaces=["moneyflow"],
            )

        assert "moneyflow" in results
        assert results["moneyflow"].status == DownloadStatus.COMPLETED
        assert results["moneyflow"].rows_fetched == 1

    def test_skip_existing_partition(self, dl, tmp_path):
        partition = tmp_path / "moneyflow" / "date=20240102"
        partition.mkdir(parents=True)
        (partition / "data.parquet").write_bytes(b"fake")

        results = dl.pull_daily_incremental(
            trade_date="20240102", interfaces=["moneyflow"],
        )
        assert results["moneyflow"].status == DownloadStatus.SKIPPED

    def test_failed_when_no_data(self, dl):
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {
                "code": 0, "data": {"fields": [], "items": []},
            }
            results = dl.pull_daily_incremental(
                trade_date="20240102", interfaces=["moneyflow"],
            )

        assert results["moneyflow"].status == DownloadStatus.FAILED

    def test_daily_basic_pull(self, dl):
        items = [["000001.SZ", "20240102"] + ["10.5"] * 16]
        payload = _tushare_response(DAILY_BASIC_COLS, items)
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = payload
            results = dl.pull_daily_incremental(
                trade_date="20240102", interfaces=["daily_basic"],
            )

        assert "daily_basic" in results
        assert results["daily_basic"].status == DownloadStatus.COMPLETED

    def test_cyq_chips_pull(self, dl):
        items = [["000001.SZ", "20240102", "10.5", "0.02"]]
        payload = _tushare_response(CYQ_CHIPS_COLS, items)
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = payload
            results = dl.pull_daily_incremental(
                trade_date="20240102", interfaces=["cyq_chips"],
            )

        assert "cyq_chips" in results
        assert results["cyq_chips"].status == DownloadStatus.COMPLETED


class TestPullBackfill:
    def test_backfill_moneyflow(self, dl):
        items = [["000001.SZ", "20240102"] + ["100"] * 18]
        payload = _tushare_response(MONEYFLOW_COLS, items)
        with patch("requests.post") as mock_post, \
             patch("time.sleep"):
            mock_post.return_value.json.return_value = payload
            total = dl.pull_backfill("moneyflow", 2024, 2024)

        assert total == 1

    def test_backfill_empty_data(self, dl):
        with patch("requests.post") as mock_post, \
             patch("time.sleep"):
            mock_post.return_value.json.return_value = {
                "code": 0, "data": {"fields": [], "items": []},
            }
            total = dl.pull_backfill("moneyflow", 2024, 2024)

        assert total == 0


class TestWatermarkAdvance:
    def test_watermark_updated_on_success(self, dl, tmp_path):
        items = [["000001.SZ", "20240102"] + ["100"] * 18]
        payload = _tushare_response(MONEYFLOW_COLS, items)
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = payload
            dl.pull_daily_incremental(trade_date="20240102", interfaces=["moneyflow"])

        from src.quant_data.meta_store import MetaStore
        with MetaStore(dl._config) as meta:
            last = meta.get_last_date("moneyflow")
            assert last == date(2024, 1, 2)
