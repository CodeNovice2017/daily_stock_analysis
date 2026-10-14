# -*- coding: utf-8 -*-
"""[personal patch 2026-10-15] 风控降档文案分化回归测试。

三个被锁定的契约:
1. 新文案在 normalize_decision_action 单动作命中(旧"减仓/卖出"复合词
   fail-closed None,导致降级样本解析丢失);
2. 新文案在判分引擎(BacktestEngine.infer_direction_expected)不得被误读
   为看多——降级说明必须在动词之后(实测"原买入建议…转防守观望"会判 up);
3. 提取器把 dashboard.risk_control 的降档上下文拷进 metadata(仅 applied
   时),供下游区分"防守性减仓"与"逻辑破坏清仓"。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.orchestrator import _adjust_operation_advice
from src.core.backtest_engine import BacktestEngine
from src.schemas.decision_action import normalize_decision_action
from src.services.decision_signal_extractor import build_decision_signal_payload_from_report
from tests.test_decision_signal_extractor import _result


class TestWordingParsers(unittest.TestCase):
    def test_hold_downgrade_wording(self):
        text = _adjust_operation_advice("观望", "buy", "hold")
        self.assertEqual(text, "持有观察（原建议已被风控下调）")
        self.assertEqual(normalize_decision_action(text), "hold")
        self.assertIn(
            BacktestEngine.infer_direction_expected(text), ("not_down", "flat")
        )

    def test_sell_downgrade_wording(self):
        text = _adjust_operation_advice("观望", "hold", "sell")
        self.assertEqual(text, "防守性卖出（原建议已被风控下调）")
        self.assertEqual(normalize_decision_action(text), "sell")
        self.assertEqual(BacktestEngine.infer_direction_expected(text), "down")

    def test_buy_to_sell_avoids_bullish_trap(self):
        # "原买入建议"若置于动词前,判分引擎会把降级样本读成 up/long(实测陷阱)
        text = _adjust_operation_advice("买入", "buy", "sell")
        self.assertEqual(normalize_decision_action(text), "sell")
        self.assertEqual(BacktestEngine.infer_direction_expected(text), "down")
        self.assertNotIn("买入", text)


class TestRiskControlMetadata(unittest.TestCase):
    def _payload(self, dashboard_risk: dict) -> dict:
        result = _result(
            operation_advice="防守性卖出（原建议已被风控下调）",
            decision_type="sell",
            sentiment_score=36,
        )
        result.action = "sell"
        result.dashboard = dict(result.dashboard)
        result.dashboard["risk_control"] = dashboard_risk
        payload = build_decision_signal_payload_from_report(
            result,
            trace_id="trace-risk-meta",
            query_source="api",
            report_type="simple",
            profile_source="auto_default",
        )
        self.assertIsNotNone(payload)
        return payload

    def test_metadata_carries_risk_control_when_applied(self):
        payload = self._payload(
            {
                "applied": True,
                "pre_risk_signal": "hold",
                "post_risk_signal": "sell",
                "downgrade_reason": "业绩预期下修",
                "narrative": "原判断中性,风控因素压倒中性判断",
            }
        )
        meta = payload.get("metadata") or {}
        risk_meta = meta.get("risk_control")
        self.assertIsNotNone(risk_meta)
        self.assertEqual(risk_meta["pre_risk_signal"], "hold")
        self.assertEqual(risk_meta["post_risk_signal"], "sell")
        self.assertEqual(risk_meta["downgrade_reason"], "业绩预期下修")

    def test_metadata_omits_risk_control_when_not_applied(self):
        payload = self._payload({"applied": False, "post_risk_signal": "sell"})
        meta = payload.get("metadata") or {}
        self.assertNotIn("risk_control", meta)


if __name__ == "__main__":
    unittest.main()
