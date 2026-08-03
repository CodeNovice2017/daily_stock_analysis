from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def get_a_share_list(source: str = "baostock") -> List[str]:
    """Return full A-share stock list. Codes in SimTradeData format (600519.SS)."""
    if source == "baostock":
        return _get_from_baostock()
    return _get_from_metadata()


def _get_from_metadata() -> List[str]:
    """Read stock list from our imported metadata."""
    import pyarrow.parquet as pq
    from pathlib import Path
    from src.quant_data.config import get_quant_config

    config = get_quant_config()
    path = Path(config.quant_data_dir) / "metadata" / "stock_metadata" / "data.parquet"
    if not path.exists():
        logger.warning("Stock metadata not found, falling back to BaoStock")
        return _get_from_baostock()
    df = pq.ParquetFile(path).read().to_pandas()
    symbols = df["symbol"].tolist()
    logger.info("Loaded %d stocks from metadata", len(symbols))
    return symbols


def _get_from_baostock() -> List[str]:
    """Fetch stock list from BaoStock API."""
    import baostock as bs

    bs.login()
    try:
        rs = bs.query_stock_basic()
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
        # Filter: only A-shares (sh.6xx, sz.0xx, sz.3xx)
        a_shares = df[
            (df["type"] == "1")  # stock type
            & df["code"].str.match(r"^(sh\.6|sz\.0|sz\.3)")
        ]
        symbols = [
            _baostock_to_simtrade(c) for c in a_shares["code"].tolist()
        ]
        logger.info("Loaded %d A-shares from BaoStock", len(symbols))
        return symbols
    finally:
        bs.logout()


def _baostock_to_simtrade(code: str) -> str:
    """Convert BaoStock format (sh.600519) to SimTradeData format (600519.SS)."""
    parts = code.split(".")
    if len(parts) != 2:
        return code
    num, exchange = parts
    if exchange == "sh":
        return f"{num}.SS"
    elif exchange == "sz":
        return f"{num}.SZ"
    return f"{num}.{exchange.upper()}"


def _simtrade_to_baostock(symbol: str) -> str:
    """Convert SimTradeData format (600519.SS) to BaoStock format (sh.600519)."""
    parts = symbol.split(".")
    if len(parts) != 2:
        return symbol
    num, exchange = parts
    if exchange == "SS":
        return f"sh.{num}"
    elif exchange == "SZ":
        return f"sz.{num}"
    return symbol.lower()
