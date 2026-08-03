from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, Optional


class SignalLevel(IntEnum):
    STRONG = 3
    MEDIUM = 2
    WEAK = 1


@dataclass
class SignalContext:
    ts_code: str
    moneyflow_net: float = 0.0
    chip_cost_95: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    prev_low: float = 0.0
    prev_high: float = 0.0
    avg_daily_volume: float = 0.0


@dataclass
class SignalResult:
    signal_name: str
    level: SignalLevel
    triggered_at: datetime
    ts_code: str
    price: float
    data: Dict[str, Any] = field(default_factory=dict)
    confidence: Optional[float] = None
