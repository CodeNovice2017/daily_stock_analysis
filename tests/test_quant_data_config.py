"""Tests for QuantDataConfig."""
import os
import pytest

from src.quant_data.config import QuantDataConfig, get_quant_config


@pytest.fixture(autouse=True)
def reset_config_singleton():
    import src.quant_data.config as cfg_mod
    old = cfg_mod._instance
    cfg_mod._instance = None
    yield
    cfg_mod._instance = old


class TestQuantDataConfig:
    def test_defaults(self):
        cfg = QuantDataConfig()
        assert cfg.quant_data_dir == "./data/quant"
        assert cfg.quant_bs_frequency == "5"
        assert cfg.quant_bs_max_workers == 4
        assert cfg.quant_tushare_rate_limit == 400
        assert cfg.quant_parquet_compression == "zstd"

    def test_custom_values(self):
        cfg = QuantDataConfig(
            quant_data_dir="/tmp/quant",
            quant_bs_max_workers=8,
            quant_tushare_rate_limit=200,
        )
        assert cfg.quant_data_dir == "/tmp/quant"
        assert cfg.quant_bs_max_workers == 8
        assert cfg.quant_tushare_rate_limit == 200

    def test_frozen(self):
        cfg = QuantDataConfig()
        with pytest.raises(AttributeError):
            cfg.quant_data_dir = "/other"

    def test_get_config_singleton(self):
        cfg1 = get_quant_config()
        cfg2 = get_quant_config()
        assert cfg1 is cfg2

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("QUANT_DATA_DIR", "/custom/quant")
        monkeypatch.setenv("QUANT_BS_MAX_WORKERS", "12")
        cfg = get_quant_config()
        assert cfg.quant_data_dir == "/custom/quant"
        assert cfg.quant_bs_max_workers == 12
