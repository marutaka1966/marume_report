"""
V2 Phase 1 tests. No live orders. No AI-Knowledge writes.
Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from v2 import DATA_UNAVAILABLE, MAIL_VERDICTS
from v2.engine import run_phase1
from v2.evaluate import evaluate_attack_iren, evaluate_defense_gold
from v2.knowledge import KnowledgeSnapshot
from v2.mail_gate import MAIL_SUPPRESSED, MAIL_WOULD_SEND, dry_run, would_send
from v2.schema import Decision, InvalidVerdictError, require_valid_verdict
from v2.targets import ATTACK_001, DEFENSE_001, KB_FILES


def _kb_ok() -> KnowledgeSnapshot:
    files = {path: "placeholder" for path in KB_FILES}
    files["Projects/Investment/Watchlist.md"] = (
        "ATTACK #001\nIREN\nWAIT\nDEFENSE #001\nゴールドファンド\nWAIT\n"
    )
    return KnowledgeSnapshot(files)


def _market_ok() -> dict:
    return {
        "IREN": {"price": 10.0, "change_pct": 1.0, "volume": 1000},
        "GOLD": {"price": 2400.0, "change_pct": 0.2, "volume": 1},
        "USDJPY": {"price": 159.0, "change_pct": 0.0, "volume": None},
        "US10Y": {"price": 4.2, "change_pct": 0.0, "volume": None},
    }


class MailGateTests(unittest.TestCase):
    def test_a_wait_suppressed(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            tag = dry_run("ATTACK #001", "WAIT")
        self.assertEqual(tag, MAIL_SUPPRESSED)
        self.assertIn("MAIL_SUPPRESSED", buf.getvalue())
        self.assertFalse(would_send("WAIT"))

    def test_b_go_would_send(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            tag = dry_run("ATTACK #001", "GO")
        self.assertEqual(tag, MAIL_WOULD_SEND)
        self.assertIn("MAIL_WOULD_SEND", buf.getvalue())
        self.assertTrue(would_send("GO"))
        for verdict in MAIL_VERDICTS:
            self.assertTrue(would_send(verdict))

    def test_d_invalid_verdict_errors(self):
        with self.assertRaises(InvalidVerdictError):
            require_valid_verdict("BUY")
        with self.assertRaises(InvalidVerdictError):
            would_send("BUY")


class EvaluateTests(unittest.TestCase):
    def test_c_missing_data_wait(self):
        kb = KnowledgeSnapshot(None, DATA_UNAVAILABLE)
        market = {"IREN": {"error": DATA_UNAVAILABLE}, "GOLD": {"error": DATA_UNAVAILABLE}}
        iren = evaluate_attack_iren(kb, market)
        gold = evaluate_defense_gold(kb, market)
        self.assertEqual(iren.verdict, "WAIT")
        self.assertEqual(gold.verdict, "WAIT")
        self.assertIn(DATA_UNAVAILABLE, iren.reason)
        self.assertIn(DATA_UNAVAILABLE, gold.reason)
        self.assertIsNone(iren.entry_price)
        self.assertIsNone(gold.entry_price)

    def test_e_iren_and_gold_not_confused(self):
        kb = _kb_ok()
        market = _market_ok()
        iren = evaluate_attack_iren(kb, market)
        gold = evaluate_defense_gold(kb, market)
        self.assertEqual(iren.test_id, ATTACK_001["test_id"])
        self.assertEqual(iren.asset, "IREN")
        self.assertNotIn("ゴールド", iren.asset)
        self.assertEqual(gold.test_id, DEFENSE_001["test_id"])
        self.assertIn("ゴールドファンド", gold.asset)
        self.assertNotEqual(iren.asset, gold.asset)
        self.assertNotIn("IREN", gold.asset)

    def test_live_path_does_not_fabricate_go(self):
        iren = evaluate_attack_iren(_kb_ok(), _market_ok())
        gold = evaluate_defense_gold(_kb_ok(), _market_ok())
        self.assertEqual(iren.verdict, "WAIT")
        self.assertEqual(gold.verdict, "WAIT")
        self.assertNotEqual(iren.verdict, "GO")
        self.assertNotEqual(gold.verdict, "GO")


class EngineTests(unittest.TestCase):
    def test_invalid_verdict_becomes_wait(self):
        bad = Decision(
            test_id="ATTACK #001",
            asset="IREN",
            verdict="BUY",
            confidence=99,
            reason=["injected"],
        )
        self.assertEqual(bad.verdict, "WAIT")
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_phase1(decisions=[bad])
        self.assertEqual(out[0]["verdict"], "WAIT")
        self.assertIn("MAIL_SUPPRESSED", buf.getvalue())

    def test_injected_go_logs_would_send(self):
        go = Decision(
            test_id="ATTACK #001",
            asset="IREN",
            verdict="GO",
            confidence=70,
            reason=["test_inject"],
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_phase1(decisions=[go])
        self.assertEqual(out[0]["verdict"], "GO")
        self.assertIn("MAIL_WOULD_SEND", buf.getvalue())

    @patch("v2.engine.fetch_market", return_value=_market_ok())
    @patch("v2.engine.load_knowledge", return_value=_kb_ok())
    def test_phase1_two_targets(self, *_mocks):
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_phase1()
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["test_id"], "ATTACK #001")
        self.assertEqual(out[1]["test_id"], "DEFENSE #001")
        self.assertEqual(out[0]["asset"], "IREN")
        self.assertIn("ゴールド", out[1]["asset"])


if __name__ == "__main__":
    unittest.main()
