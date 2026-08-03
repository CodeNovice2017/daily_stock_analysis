"""Tests for scheduler and config."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import date

from src.quant_data.config import QuantDataConfig, get_quant_config
from src.quant_data.scheduler import QuantDataScheduler
from src.quant_data.types import DownloadStatus, DownloadResult, DownloadTask


class TestScheduler:
    def _make_result(self, name, status, rows=10):
        task = DownloadTask(
            symbol="ALL", start_date="20240102", end_date="20240102",
            frequency="daily", source="tushare", interface=name,
        )
        return DownloadResult(task=task, status=status, rows_fetched=rows)

    def test_run_daily_delegates_to_downloader(self, tmp_path):
        config = QuantDataConfig(quant_data_dir=str(tmp_path))
        mock_dl = MagicMock()
        mock_dl.pull_daily_incremental.return_value = {
            "moneyflow": self._make_result("moneyflow", DownloadStatus.COMPLETED),
            "daily_basic": self._make_result("daily_basic", DownloadStatus.COMPLETED),
        }
        with patch.object(QuantDataScheduler, "__init__", lambda self, cfg=None: None):
            sched = QuantDataScheduler()
            sched._config = config
            sched._downloader = mock_dl
            results = sched.run_daily("20240102")

        assert "moneyflow" in results
        assert results["moneyflow"].status == DownloadStatus.COMPLETED
        mock_dl.pull_daily_incremental.assert_called_once_with(trade_date="20240102")

    def test_run_daily_default_trade_date(self, tmp_path):
        config = QuantDataConfig(quant_data_dir=str(tmp_path))
        mock_dl = MagicMock()
        mock_dl.pull_daily_incremental.return_value = {}
        with patch.object(QuantDataScheduler, "__init__", lambda self, cfg=None: None):
            sched = QuantDataScheduler()
            sched._config = config
            sched._downloader = mock_dl
            sched.run_daily()

        mock_dl.pull_daily_incremental.assert_called_once_with(trade_date=None)
