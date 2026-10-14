# -*- coding: utf-8 -*-
"""[personal patch 2026-10-15] sniper point validation regression tests.

数组样式点位与止损≥目标倒挂在解析层判无效(extract→DB NULL),
在 dashboard 层清洗为哨兵"—"(阻断 support_levels 自动回填)。
止损==买点为突破型贴线止损,保留仅告警。
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.utils.sniper_points import (
    SNIPER_SENTINEL,
    extract_sniper_points,
    sanitize_sniper_points_in_place,
)


class TestExtractValidation(unittest.TestCase):
    def test_array_style_entry_becomes_none(self):
        result = SimpleNamespace(
            get_sniper_points=lambda: {
                "ideal_buy": "[71.7 70.5 68.5]",
                "stop_loss": 68.9,
                "take_profit": 80.0,
            },
            dashboard={},
            raw_response={},
        )
        points = extract_sniper_points(result)
        self.assertIsNone(points["ideal_buy"])
        self.assertEqual(points["stop_loss"], 68.9)

    def test_inverted_stop_target_nullifies_stop(self):
        # 实例:588170 2026-10-08 stop=0.93 > target=0.91 字段倒挂
        result = SimpleNamespace(
            get_sniper_points=lambda: {
                "ideal_buy": 0.87,
                "stop_loss": 0.93,
                "take_profit": 0.91,
            },
            dashboard={},
            raw_response={},
        )
        points = extract_sniper_points(result)
        self.assertIsNone(points["stop_loss"])
        self.assertEqual(points["take_profit"], 0.91)

    def test_stop_equal_entry_is_kept(self):
        # 突破型贴线止损(站上 X 追入,止损 X 下方)合法,不判无效
        result = SimpleNamespace(
            get_sniper_points=lambda: {
                "ideal_buy": 0.898,
                "stop_loss": 0.898,
                "take_profit": 0.95,
            },
            dashboard={},
            raw_response={},
        )
        points = extract_sniper_points(result)
        self.assertEqual(points["stop_loss"], 0.898)


class TestSanitizeInPlace(unittest.TestCase):
    def test_sentinel_written_for_array_and_inversion(self):
        sniper = {
            "ideal_buy": "[71.7 70.5 68.5]",
            "stop_loss": 0.93,
            "take_profit": 0.91,
        }
        sanitize_sniper_points_in_place(sniper)
        self.assertEqual(sniper["ideal_buy"], SNIPER_SENTINEL)
        self.assertEqual(sniper["stop_loss"], SNIPER_SENTINEL)
        self.assertEqual(sniper["take_profit"], 0.91)

    def test_empty_values_left_alone(self):
        # 真缺失保持原样,允许 pipeline 既有兜底逻辑工作
        sniper = {"ideal_buy": None, "stop_loss": "", "take_profit": "N/A"}
        sanitize_sniper_points_in_place(sniper)
        self.assertIsNone(sniper["ideal_buy"])
        self.assertEqual(sniper["stop_loss"], "")
        self.assertEqual(sniper["take_profit"], "N/A")

    def test_valid_values_untouched(self):
        sniper = {
            "ideal_buy": 10.0,
            "secondary_buy": 9.5,
            "stop_loss": 9.0,
            "take_profit": 11.0,
        }
        sanitize_sniper_points_in_place(sniper)
        self.assertEqual(sniper["stop_loss"], 9.0)

    def test_sentinel_blocks_pipeline_backfill_detection(self):
        # 哨兵不得被识别为"缺失",否则会触发 support_levels 回填
        from src.core.pipeline import StockAnalysisPipeline

        self.assertFalse(
            StockAnalysisPipeline._is_agent_field_missing(SNIPER_SENTINEL, scalar=True)
        )


if __name__ == "__main__":
    unittest.main()
