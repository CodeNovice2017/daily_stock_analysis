# -*- coding: utf-8 -*-
"""Helpers for parsing report sniper-point price values."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


SNIPER_KEYS = ("ideal_buy", "secondary_buy", "stop_loss", "take_profit")

# [personal patch 2026-10-15] 校验哨兵:dashboard 中数组样式/止损目标倒挂的点位
# 被清洗为该值。"—" 不在 pipeline._is_agent_field_missing 的 placeholder 集合内
# → 不会触发 support_levels[0] 自动回填;而 parse_sniper_value 将 "—" 映射为
# None → 落库列自动为 NULL。防回填与 DB 干净一举两得。
SNIPER_SENTINEL = "—"


def parse_sniper_value(value: Any) -> Optional[float]:
    """Parse a sniper point value from report text into a positive price."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if parsed > 0 else None

    text = str(value).replace(",", "").replace("，", "").strip()
    if not text or text in {"-", "—", "N/A"}:
        return None

    try:
        parsed = float(text)
        return parsed if parsed > 0 else None
    except ValueError:
        pass

    colon_pos = max(text.rfind("："), text.rfind(":"))
    yuan_pos = text.find("元", colon_pos + 1 if colon_pos != -1 else 0)
    if yuan_pos != -1:
        segment_start = colon_pos + 1 if colon_pos != -1 else 0
        segment = text[segment_start:yuan_pos]
        valid_numbers = []
        for match in re.finditer(r"-?\d+(?:\.\d+)?", segment):
            start_idx = match.start()
            if start_idx >= 2 and segment[start_idx - 2:start_idx].upper() == "MA":
                continue
            valid_numbers.append(match.group())
        if valid_numbers:
            try:
                parsed = abs(float(valid_numbers[-1]))
                return parsed if parsed > 0 else None
            except ValueError:
                pass

    paren_pos = len(text)
    for paren_char in ("(", "（"):
        pos = text.find(paren_char)
        if pos != -1:
            paren_pos = min(paren_pos, pos)
    search_text = text[:paren_pos].strip() or text

    valid_numbers = []
    for match in re.finditer(r"\d+(?:\.\d+)?", search_text):
        start_idx = match.start()
        if start_idx >= 2 and search_text[start_idx - 2:start_idx].upper() == "MA":
            continue
        valid_numbers.append(match.group())
    if valid_numbers:
        try:
            parsed = float(valid_numbers[-1])
            return parsed if parsed > 0 else None
        except ValueError:
            pass
    return None


def extract_sniper_points(result: Any) -> Dict[str, Optional[float]]:
    """Extract normalized sniper-point prices from a completed analysis result."""

    raw_points: Mapping[str, Any] = {}

    if hasattr(result, "get_sniper_points"):
        candidate = result.get_sniper_points() or {}
        if isinstance(candidate, Mapping):
            raw_points = candidate

    if not _has_any_sniper_value(raw_points):
        dashboard = getattr(result, "dashboard", None)
        if isinstance(dashboard, Mapping):
            raw_points = find_sniper_points(dashboard) or raw_points

    if not _has_any_sniper_value(raw_points):
        raw_response = getattr(result, "raw_response", None)
        if isinstance(raw_response, Mapping):
            raw_points = find_sniper_points(raw_response) or raw_points

    return _parse_with_validation(raw_points)


def _is_array_style(value: Any) -> bool:
    """LLM 偶发输出区间数组(如 "[71.7 70.5 68.5]"),取任一端点都是猜测。"""

    if isinstance(value, (list, tuple, set)):
        return True
    if isinstance(value, str):
        return value.strip().startswith("[")
    return False


def _parse_with_validation(raw_points: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    """带跨字段校验的解析:数组样式与止损≥目标(多头世界倒挂)一律判无效。

    止损==买点不判无效(突破型"贴线止损"合法),仅告警供人工复核。
    """

    parsed: Dict[str, Optional[float]] = {}
    for key in SNIPER_KEYS:
        raw = raw_points.get(key)
        parsed[key] = None if _is_array_style(raw) else parse_sniper_value(raw)

    stop = parsed.get("stop_loss")
    target = parsed.get("take_profit")
    if stop is not None and target is not None and stop >= target:
        parsed["stop_loss"] = None

    if stop is not None and stop in (parsed.get("ideal_buy"), parsed.get("secondary_buy")):
        logger.warning(
            "sniper stop_loss equals entry point (%s); 突破型贴线止损?保留但请人工复核",
            stop,
        )
    return parsed


def sanitize_sniper_points_in_place(sniper_points: Any) -> None:
    """就地清洗 dashboard 的 sniper_points(在 pipeline 兜底之前调用)。

    值非空但解析无效(数组/倒挂)→ SNIPER_SENTINEL:既阻断 support_levels
    自动回填,又让下游 parse 得到 None。值为空则保持空(真缺失允许兜底)。
    """

    if not isinstance(sniper_points, Mapping):
        return
    parsed = _parse_with_validation(sniper_points)
    explicit_null_tokens = {"-", "—", "N/A"}
    for key in SNIPER_KEYS:
        raw = sniper_points.get(key)
        if isinstance(raw, str) and raw.strip() in explicit_null_tokens:
            # LLM 的显式空值(报告常渲染 "N/A"),parse 已映射 None,保持原样
            continue
        if parsed.get(key) is None and raw not in (None, ""):
            sniper_points[key] = SNIPER_SENTINEL


def _has_any_sniper_value(points: Mapping[str, Any]) -> bool:
    return any(points.get(key) not in (None, "") for key in SNIPER_KEYS)


def find_sniper_points(data: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    if not isinstance(data, Mapping):
        return None

    if any(key in data for key in SNIPER_KEYS):
        return data

    sniper_points = data.get("sniper_points")
    if isinstance(sniper_points, Mapping) and sniper_points:
        return sniper_points

    battle_plan = data.get("battle_plan")
    if isinstance(battle_plan, Mapping):
        sniper_points = battle_plan.get("sniper_points")
        if isinstance(sniper_points, Mapping) and sniper_points:
            return sniper_points

    inner_dashboard = data.get("dashboard")
    if isinstance(inner_dashboard, Mapping):
        found = find_sniper_points(inner_dashboard)
        if found:
            return found

    return None
