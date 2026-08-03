# -*- coding: utf-8 -*-
"""
涨停余温评估引擎（纯逻辑，无 IO 依赖）

实现「涨停余温战法」的三条件评估和评分：
  条件1 - 价格底线：3 日收盘价 >= 涨停价 × ratio
  条件2 - 新高动作：≥2 日盘中创新高（高于涨停日最高价）
  条件3 - 量能控制：3 日均量 ∈ [涨停日量 × vol_low, 涨停日量 × vol_high]

三选二入围，综合评分 0-100。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LimitUpReference:
    """涨停日参考数据。"""

    close: float
    high: float
    volume: float
    price_floor_ratio: float = 0.97
    volume_low_ratio: float = 0.40
    volume_high_ratio: float = 1.20
    min_conditions: int = 2
    # 单日放量熔断：任一后续交易日成交量 > 涨停日量 × 此值 → 一票否决（出货信号）。
    # 0 表示关闭。默认 1.2 对应「放量超 120% 是分批出货」。
    volume_surge_ratio: float = 1.20


@dataclass(frozen=True)
class TrackingDay:
    """涨停后某个交易日数据。"""

    date: str
    close: float
    high: float
    volume: float


@dataclass
class ConditionResult:
    """单个条件评估结果。"""

    name: str
    passed: bool
    score: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """完整评估结果。"""

    qualified: bool
    score: int
    conditions: List[ConditionResult]
    conditions_met: int
    should_evaluate: bool
    summary: str = ""


# 板块分类 → 涨停阈值
BOARD_LIMIT_THRESHOLDS: Dict[str, float] = {
    "main": 0.10,
    "gem": 0.20,
    "star": 0.20,
    "bse": 0.30,
}


def classify_board(code: str) -> str:
    """根据代码前缀判断板块类型。"""
    c = code.strip()
    if c.startswith(("300", "301")):
        return "gem"
    if c.startswith("688"):
        return "star"
    if c.startswith(("8", "9")) and len(c) == 6:
        return "bse"
    return "main"


def is_limit_up(
    pct_chg: float,
    board_type: Optional[str] = None,
    code: Optional[str] = None,
) -> bool:
    """判断是否达到涨停。"""
    if board_type is None:
        board_type = classify_board(code or "")
    threshold = BOARD_LIMIT_THRESHOLDS.get(board_type, 0.10)
    return pct_chg >= (threshold * 100 - 0.5)


def evaluate(
    reference: LimitUpReference,
    tracking_days: List[TrackingDay],
    expected_days: int = 3,
) -> EvaluationResult:
    """评估涨停余温三条件。

    tracking_days 不足 expected_days 时返回 should_evaluate=False，
    表示数据还不完整，需要继续等待。
    """
    if len(tracking_days) < expected_days:
        return EvaluationResult(
            qualified=False,
            score=0,
            conditions=[],
            conditions_met=0,
            should_evaluate=False,
            summary=f"数据不足: {len(tracking_days)}/{expected_days} 天",
        )

    days = tracking_days[:expected_days]

    # 硬熔断：任一后续交易日单日放量 > 涨停日量 × surge_ratio → 一票否决（出货信号）。
    # 这是「宁缺毋滥」的核心闸门：即便价格守住、新高不断，出现单日放量出货也直接否决。
    if reference.volume > 0 and reference.volume_surge_ratio > 0:
        max_ratio = max(d.volume / reference.volume for d in days if d.volume > 0)
        if max_ratio > reference.volume_surge_ratio:
            c1 = _evaluate_price_floor(reference, days)
            c2 = _evaluate_new_highs(reference, days)
            c3 = _evaluate_volume(reference, days)
            conditions = [c1, c2, c3]
            met_count = sum(1 for c in conditions if c.passed)
            return EvaluationResult(
                qualified=False,
                score=0,
                conditions=conditions,
                conditions_met=met_count,
                should_evaluate=True,
                summary=f"一票否决: 单日放量 {max_ratio:.2f}× > {reference.volume_surge_ratio}×（疑似出货）",
            )

    c1 = _evaluate_price_floor(reference, days)
    c2 = _evaluate_new_highs(reference, days)
    c3 = _evaluate_volume(reference, days)
    conditions = [c1, c2, c3]
    met_count = sum(1 for c in conditions if c.passed)

    if met_count < reference.min_conditions:
        return EvaluationResult(
            qualified=False,
            score=0,
            conditions=conditions,
            conditions_met=met_count,
            should_evaluate=True,
            summary=f"不满足最低条件数 {met_count}/{reference.min_conditions}",
        )

    total = _compute_composite_score(conditions, met_count)
    parts = [c.name for c in conditions if c.passed]
    return EvaluationResult(
        qualified=True,
        score=total,
        conditions=conditions,
        conditions_met=met_count,
        should_evaluate=True,
        summary=f"满足 {met_count}/3 ({'+'.join(parts)}), 评分 {total}",
    )


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------

def _evaluate_price_floor(
    ref: LimitUpReference,
    days: List[TrackingDay],
) -> ConditionResult:
    """条件1：价格底线 — 3 日收盘价 >= 涨停价 × price_floor_ratio。"""
    threshold = ref.close * ref.price_floor_ratio
    all_hold = all(d.close >= threshold for d in days)

    above_close = all(d.close >= ref.close for d in days)
    min_pct = min(d.close / ref.close for d in days)

    if all_hold and above_close:
        strength = 34
    elif all_hold:
        strength = min(34, int((min_pct - ref.price_floor_ratio) / (1 - ref.price_floor_ratio) * 34))
    else:
        strength = 0

    return ConditionResult(
        name="price_hold",
        passed=all_hold,
        score=strength,
        details={
            "threshold": round(threshold, 2),
            "min_close": round(min(d.close for d in days), 2),
            "min_pct": round(min_pct * 100, 2),
        },
    )


def _evaluate_new_highs(
    ref: LimitUpReference,
    days: List[TrackingDay],
) -> ConditionResult:
    """条件2：新高动作 — ≥2 日盘中创新高。"""
    new_high_count = sum(1 for d in days if d.high > ref.high)
    passed = new_high_count >= 2

    if new_high_count >= 3:
        strength = 34
    elif new_high_count == 2:
        strength = 28
    else:
        strength = 0

    return ConditionResult(
        name="new_highs",
        passed=passed,
        score=strength,
        details={
            "new_high_days": new_high_count,
            "total_days": len(days),
        },
    )


def _evaluate_volume(
    ref: LimitUpReference,
    days: List[TrackingDay],
) -> ConditionResult:
    """条件3：量能控制 — 3 日均量 ∈ [vol_low, vol_high] × 涨停日量。"""
    if ref.volume <= 0:
        return ConditionResult(
            name="volume",
            passed=False,
            score=0,
            details={"reason": "limit_up_volume is zero"},
        )

    avg_vol = sum(d.volume for d in days) / len(days)
    ratio = avg_vol / ref.volume
    low = ref.volume_low_ratio
    high = ref.volume_high_ratio
    in_range = low <= ratio <= high

    if not in_range:
        strength = 0
    else:
        optimal = 0.55
        max_dist = max(optimal - low, high - optimal)
        dist = abs(ratio - optimal)
        strength = max(0, min(34, int(34 * (1 - dist / max_dist))))

    return ConditionResult(
        name="volume",
        passed=in_range,
        score=strength,
        details={
            "avg_volume": round(avg_vol, 0),
            "volume_ratio": round(ratio, 3),
            "range": [low, high],
        },
    )


def _compute_composite_score(
    conditions: List[ConditionResult],
    met_count: int,
) -> int:
    """综合评分：取最佳两项条件分 + 全部满足加 bonus。"""
    scores = sorted((c.score for c in conditions if c.passed), reverse=True)
    while len(scores) < 2:
        scores.append(0)
    base = int(scores[0] + scores[1])
    bonus = 32 if met_count == 3 else 0
    return min(100, base + bonus)
