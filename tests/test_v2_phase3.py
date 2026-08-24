"""
V2 Phase 3-A tests. No live orders. No AI-Knowledge writes.
Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import inspect
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from v2 import DATA_UNAVAILABLE, LIVE_VERDICTS
from v2 import knowledge as knowledge_mod
from v2.engine import run_phase1
from v2.evaluate import evaluate_attack_iren, evaluate_defense_gold
from v2.knowledge import KnowledgeSnapshot
from v2.logstore import write_run
from v2.mail_gate import MAIL_SUPPRESSED, MAIL_WOULD_SEND, dry_run
from v2.schema import Decision
from v2.targets import (
    ATTACK_001,
    CONFIRMED_TEST_IDS,
    DEFENSE_001,
    KB_FILES,
    TARGETS,
    is_confirmed_test_id,
)


def _kb_ok() -> KnowledgeSnapshot:
    files = {path: "placeholder" for path in KB_FILES}
    files["Projects/Investment/Watchlist.md"] = (
        "ATTACK #001\nIREN\nWAIT\nDEFENSE #001\nゴールドファンド\nWAIT\n"
    )
    return KnowledgeSnapshot(files)


def _kb_without_test_ids() -> KnowledgeSnapshot:
    files = {path: "placeholder" for path in KB_FILES}
    files["Projects/Investment/Watchlist.md"] = "監視のみ。Test ID なし。\n"
    return KnowledgeSnapshot(files)


def _market_ok() -> dict:
    return {
        "IREN": {"price": 10.0, "change_pct": 1.0, "volume": 1000},
        "GOLD": {"price": 2400.0, "change_pct": 0.2, "volume": 1},
        "USDJPY": {"price": 159.0, "change_pct": 0.0, "volume": None},
        "US10Y": {"price": 4.2, "change_pct": 0.0, "volume": None},
    }


def _complete_indicators(*, spike: bool = False) -> dict:
    return {
        "sma20": 10.0,
        "rsi14": 55.0,
        "volume_spike": spike,
    }


class NormalPathTests(unittest.TestCase):
    def test_n1_confirmed_ids_are_not_confused(self):
        iren = evaluate_attack_iren(_kb_ok(), _market_ok())
        gold = evaluate_defense_gold(_kb_ok(), _market_ok())
        self.assertEqual(iren.test_id, ATTACK_001["test_id"])
        self.assertEqual(iren.asset, ATTACK_001["asset"])
        self.assertEqual(gold.test_id, DEFENSE_001["test_id"])
        self.assertEqual(gold.asset, DEFENSE_001["asset"])
        self.assertNotEqual(iren.asset, gold.asset)

    def test_n2_no_indicators_is_wait(self):
        iren = evaluate_attack_iren(_kb_ok(), _market_ok())
        gold = evaluate_defense_gold(_kb_ok(), _market_ok())
        self.assertEqual(iren.verdict, "WAIT")
        self.assertEqual(gold.verdict, "WAIT")

    def test_n3_calm_indicators_is_watch(self):
        iren = evaluate_attack_iren(
            _kb_ok(), _market_ok(), indicators=_complete_indicators()
        )
        self.assertEqual(iren.verdict, "WATCH")
        self.assertNotEqual(iren.verdict, "GO")

    def test_n4_spike_without_chase_is_go_candidate(self):
        iren = evaluate_attack_iren(
            _kb_ok(),
            _market_ok(),
            indicators=_complete_indicators(spike=True),
        )
        self.assertEqual(iren.verdict, "GO_CANDIDATE")
        self.assertNotEqual(iren.verdict, "GO")

    def test_n5_sharp_move_is_alert(self):
        market = _market_ok()
        market["IREN"] = {"price": 12.0, "change_pct": 9.0, "volume": 1000}
        iren = evaluate_attack_iren(
            _kb_ok(),
            market,
            indicators=_complete_indicators(spike=True),
        )
        self.assertEqual(iren.verdict, "ALERT")
        self.assertNotEqual(iren.verdict, "GO_CANDIDATE")
        self.assertNotEqual(iren.verdict, "GO")

    def test_n6_and_n8_history_and_mail_gate(self):
        self.assertEqual(dry_run("ATTACK #001", "WATCH"), MAIL_SUPPRESSED)
        self.assertEqual(dry_run("ATTACK #001", "GO_CANDIDATE"), MAIL_WOULD_SEND)
        decision = evaluate_attack_iren(
            _kb_ok(),
            _market_ok(),
            indicators=_complete_indicators(spike=True),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_run([decision.to_dict()], log_dir=tmp, market=_market_ok())
            self.assertTrue(path.is_file())
            self.assertTrue(str(path.resolve()).startswith(str(Path(tmp).resolve())))
            self.assertTrue(path.name.endswith(".json"))
            document = json.loads(path.read_text(encoding="utf-8"))
            row = document["decisions"][0]
            for key in ("test_id", "verdict", "reason", "inputs_used", "indicators", "missing"):
                self.assertIn(key, row)
            self.assertIn("date", document)

    def test_n7_watchlist_is_read_not_written(self):
        kb = _kb_ok()
        before = kb.watchlist_text()
        evaluate_attack_iren(kb, _market_ok())
        self.assertEqual(kb.watchlist_text(), before)
        self.assertTrue(kb.has_test_id("ATTACK #001"))


class AbnormalPathTests(unittest.TestCase):
    def test_e1_missing_knowledge_is_wait(self):
        kb = KnowledgeSnapshot(None, DATA_UNAVAILABLE)
        iren = evaluate_attack_iren(kb, _market_ok(), indicators=_complete_indicators(spike=True))
        gold = evaluate_defense_gold(kb, _market_ok(), indicators=_complete_indicators(spike=True))
        self.assertEqual(iren.verdict, "WAIT")
        self.assertEqual(gold.verdict, "WAIT")
        self.assertIn(DATA_UNAVAILABLE, iren.reason)
        self.assertIn(DATA_UNAVAILABLE, gold.reason)

    def test_e2_missing_quotes_is_wait(self):
        market = {
            "IREN": {"error": DATA_UNAVAILABLE},
            "GOLD": {"error": DATA_UNAVAILABLE},
        }
        iren = evaluate_attack_iren(_kb_ok(), market)
        gold = evaluate_defense_gold(_kb_ok(), market)
        self.assertEqual(iren.verdict, "WAIT")
        self.assertEqual(gold.verdict, "WAIT")
        self.assertIn("IREN_quote", iren.missing)
        self.assertIn("GOLD_quote", gold.missing)

    def test_e3_buy_and_order_become_wait(self):
        buy = Decision("ATTACK #001", "IREN", "BUY", 90)
        order = Decision("ATTACK #001", "IREN", "ORDER", 90)
        self.assertEqual(buy.verdict, "WAIT")
        self.assertEqual(order.verdict, "WAIT")

    def test_e4_unconfirmed_names_are_not_targets(self):
        self.assertFalse(is_confirmed_test_id("ソニーFG"))
        self.assertEqual(CONFIRMED_TEST_IDS, ("ATTACK #001", "DEFENSE #001"))
        self.assertEqual(len(TARGETS), 2)

    def test_e5_log_rejects_knowledge_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            forbidden = Path(tmp) / "AI-Knowledge" / "logs"
            forbidden.mkdir(parents=True)
            with self.assertRaises(ValueError):
                write_run([], log_dir=forbidden)

    def test_e6_missing_watchlist_id_is_wait_without_creating_note(self):
        kb = _kb_without_test_ids()
        before = kb.watchlist_text()
        iren = evaluate_attack_iren(kb, _market_ok(), indicators=_complete_indicators())
        self.assertEqual(iren.verdict, "WAIT")
        self.assertIn("watchlist_iren", iren.missing)
        self.assertEqual(kb.watchlist_text(), before)
        self.assertFalse(kb.has_test_id("ATTACK #001"))


class GoForbiddenTests(unittest.TestCase):
    def test_live_evaluate_never_returns_go(self):
        cases = [
            evaluate_attack_iren(_kb_ok(), _market_ok()),
            evaluate_defense_gold(_kb_ok(), _market_ok()),
            evaluate_attack_iren(_kb_ok(), _market_ok(), indicators=_complete_indicators()),
            evaluate_attack_iren(
                _kb_ok(), _market_ok(), indicators=_complete_indicators(spike=True)
            ),
            evaluate_attack_iren(
                KnowledgeSnapshot(None, DATA_UNAVAILABLE),
                {"IREN": {"error": DATA_UNAVAILABLE}},
                indicators=_complete_indicators(spike=True),
            ),
        ]
        market = _market_ok()
        market["IREN"] = {"price": 12.0, "change_pct": 9.0, "volume": 1000}
        cases.append(
            evaluate_attack_iren(_kb_ok(), market, indicators=_complete_indicators(spike=True))
        )
        for decision in cases:
            self.assertNotEqual(decision.verdict, "GO")
            self.assertIn(decision.verdict, LIVE_VERDICTS)

    @patch("v2.engine.fetch_market", return_value=_market_ok())
    @patch("v2.engine.load_knowledge", return_value=_kb_ok())
    def test_live_engine_never_returns_go(self, *_mocks):
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_phase1(log_dir=False)
        self.assertEqual(len(out), 2)
        for row in out:
            self.assertNotEqual(row["verdict"], "GO")
            self.assertIn(row["verdict"], LIVE_VERDICTS)
            self.assertNotIn("ORDER", row["verdict"])


class KnowledgeWriteForbiddenTests(unittest.TestCase):
    def test_knowledge_module_has_no_write_helpers(self):
        names = {name.lower() for name in dir(knowledge_mod)}
        for banned in ("write", "put", "patch", "delete", "commit", "save"):
            self.assertNotIn(banned, names)
        source = Path(inspect.getfile(knowledge_mod)).read_text(encoding="utf-8")
        self.assertIn('method="GET"', source)
        self.assertNotIn("method=\"PUT\"", source)
        self.assertNotIn("method=\"PATCH\"", source)
        self.assertNotIn("method=\"DELETE\"", source)
        self.assertNotIn("method=\"POST\"", source)

    def test_evaluate_does_not_change_snapshot_files(self):
        kb = _kb_ok()
        before = dict(kb.files)
        evaluate_attack_iren(kb, _market_ok())
        evaluate_defense_gold(kb, _market_ok())
        self.assertEqual(kb.files, before)


class DataUnavailableWaitTests(unittest.TestCase):
    def test_unavailable_stays_wait_even_with_indicators(self):
        kb = KnowledgeSnapshot(None, DATA_UNAVAILABLE)
        market = {"IREN": {"error": DATA_UNAVAILABLE}, "GOLD": {"error": DATA_UNAVAILABLE}}
        iren = evaluate_attack_iren(kb, market, indicators=_complete_indicators(spike=True))
        gold = evaluate_defense_gold(kb, market, indicators=_complete_indicators(spike=True))
        self.assertEqual(iren.verdict, "WAIT")
        self.assertEqual(gold.verdict, "WAIT")
        self.assertEqual(iren.confidence, 0)
        self.assertEqual(gold.confidence, 0)
        self.assertIsNone(iren.entry_price)
        self.assertIsNone(gold.entry_price)
        self.assertNotEqual(iren.verdict, "GO_CANDIDATE")
        self.assertNotEqual(iren.verdict, "WATCH")


class LogStoreTests(unittest.TestCase):
    def test_required_history_fields_and_not_canonical_notes(self):
        decision = evaluate_attack_iren(
            _kb_ok(),
            _market_ok(),
            indicators=_complete_indicators(spike=True),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_run([decision.to_dict()], log_dir=tmp, market=_market_ok())
            self.assertNotIn("AI-Knowledge", path.parts)
            self.assertNotIn("Watchlist.md", path.parts)
            self.assertNotIn("Performance.md", path.parts)
            self.assertNotIn("StrategyBank.md", path.parts)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("date", document)
            row = document["decisions"][0]
            for key in ("test_id", "verdict", "reason", "inputs_used", "indicators", "missing"):
                self.assertIn(key, row)

    def test_rejects_canonical_markdown_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            forbidden = Path(tmp) / "Watchlist.md"
            with self.assertRaises(ValueError):
                write_run([], log_dir=forbidden)


if __name__ == "__main__":
    unittest.main()
