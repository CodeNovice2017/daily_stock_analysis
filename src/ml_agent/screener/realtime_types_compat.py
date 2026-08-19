# -*- coding: utf-8 -*-
"""兼容层：复用 data_provider 的 safe_float。"""

from __future__ import annotations

import math
from typing import Any


def safe_float(val: Any, default: float = 0.0) -> float:
    """安全转 float，None/NaN/异常 → default。"""
    try:
        if val is None:
            return default
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default
