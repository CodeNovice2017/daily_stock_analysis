# -*- coding: utf-8 -*-
"""涨停余温扫描器配置 — 自读环境变量，不侵入上游 Config。"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


def _env_int(key: str, default: int, *, minimum: int = 0, maximum: int = 9999) -> int:
    try:
        val = int(os.getenv(key, str(default)))
        return max(minimum, min(maximum, val))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float, *, minimum: float = 0.0, maximum: float = 9999.0) -> float:
    try:
        val = float(os.getenv(key, str(default)))
        return max(minimum, min(maximum, val))
    except (ValueError, TypeError):
        return default


@dataclass
class ScreenerConfig:
    """涨停余温扫描器配置。"""

    enabled: bool = False
    track_days: int = 3
    price_hold_ratio: float = 0.97
    volume_low: float = 0.40
    volume_high: float = 1.0
    volume_surge_ratio: float = 1.20
    min_conditions: int = 2
    max_age_days: int = 10

    @classmethod
    def from_env(cls) -> "ScreenerConfig":
        return cls(
            enabled=_env_bool("LIMIT_UP_SCREENER_ENABLED"),
            track_days=_env_int("LIMIT_UP_SCREENER_TRACK_DAYS", 3, minimum=2, maximum=10),
            price_hold_ratio=_env_float("LIMIT_UP_SCREENER_PRICE_HOLD_RATIO", 0.97, minimum=0.8, maximum=1.0),
            volume_low=_env_float("LIMIT_UP_SCREENER_VOLUME_LOW", 0.40, minimum=0.1, maximum=1.0),
            # 严格模式：均量上限 1.0（必须真正缩量，非持平/放量）
            volume_high=_env_float("LIMIT_UP_SCREENER_VOLUME_HIGH", 1.0, minimum=0.5, maximum=3.0),
            # 单日放量熔断：任一后续交易日量 > 涨停日 × 此值 → 一票否决。0 关闭。
            volume_surge_ratio=_env_float("LIMIT_UP_SCREENER_VOLUME_SURGE_RATIO", 1.20, minimum=0.0, maximum=5.0),
            min_conditions=_env_int("LIMIT_UP_SCREENER_MIN_CONDITIONS", 2, minimum=1, maximum=3),
            max_age_days=_env_int("LIMIT_UP_SCREENER_MAX_AGE_DAYS", 10, minimum=3, maximum=30),
        )
