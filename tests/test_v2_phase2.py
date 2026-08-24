"""
V2 Phase 2 tests. No live orders. No AI-Knowledge writes.
Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from v2 import DATA_UNAVAILABLE, LIVE_VERDICTS
from v2.engine import run_phase1
from v2.evaluate import evaluate_attack_iren, evaluate_defense_gold
from v2.indicators import from_quote, rsi, sma, volume_spike
from v2.knowledge import KnowledgeSnapshot
from v2.logstore import write_run
from v2.mail_gate import MAIL_SUPPRESSED, MAIL_WOULD_SEND, dry_run
from v2.schema import Decision, require_valid_verdict
from v2.targets import KB_FILES


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


def _closes(n: int, start: float = 10.0, step: float = 0.1) -> list[float]:
    return [start + step * i for i in range(n)]


def _complete_indicators(*, spike: bool = False) -> dict:
    return {
        "sma20": 10.0,
        "rsi14": 55.0,
        "volume_spike": spike,
    }


class SchemaTests(unittest.TestCase):
    def test_watch_and_go_candidate_are_valid(self):
        require_valid_verdict("WATCH")
        require_valid_verdict("GO_CANDIDATE")
        watch = Decision("ATTACK #001", "IREN", "WATCH", 40)
        candidate = Decision("ATTACK #001", "IREN", "GO_CANDIDATE", 40)
        self.assertEqual(watch.verdict, "WATCH")
        self.assertEqual(candidate.verdict, "GO_CANDIDATE")

    def test_invalid_stays_wait(self):
        decision = Decision("ATTACK #001", "IREN", "BUY", 90)
        self.assertEqual(decision.verdict, "WAIT")


class IndicatorTests(unittest.TestCase):
    def test_short_series_is_none(self):
        short = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertIsNone(sma(short, 20))
        self.assertIsNone(rsi(short, 14))
        self.assertIsNone(volume_spike(short, 20))
        self.assertIsNone(from_quote({"price": 1.0}))
        self.assertIsNone(from_quote({"error": DATA_UNAVAILABLE}))

    def test_computes_when_series_is_long_enough(self):
        closes = _closes(25)
        volumes = [100.0] * 20 + [250.0]
        self.assertIsNotNone(sma(closes, 20))
        self.assertIsNotNone(rsi(closes, 14))
        self.assertTrue(volume_spike(volumes, 20, 2.0))
        payload = from_quote({"closes": closes, "volumes": volumes, "price": closes[-1]})
        self.assertIsNotNone(payload)
        self.assertIn("sma20", payload)
        self.assertIn("rsi14", payload)
        self.assertTrue(payload["volume_spike"])


class EvaluatePhase2Tests(unittest.TestCase):
    def test_missing_data_is_wait(self):
        kb = KnowledgeSnapshot(None, DATA_UNAVAILABLE)
        market = {"IREN": {"error": DATA_UNAVAILABLE}, "GOLD": {"error": DATA_UNAVAILABLE}}
        iren = evaluate_attack_iren(kb, market, indicators=_complete_indicators(spike=True))
        gold = evaluate_defense_gold(kb, market, indicators=_complete_indicators(spike=True))
        self.assertEqual(iren.verdict, "WAIT")
        self.assertEqual(gold.verdict, "WAIT")
        self.assertNotEqual(iren.verdict, "GO")
        self.assertNotEqual(iren.verdict, "GO_CANDIDATE")
        self.assertIn(DATA_UNAVAILABLE, iren.reason)

    def test_no_indicators_stays_wait(self):
        iren = evaluate_attack_iren(_kb_ok(), _market_ok())
        gold = evaluate_defense_gold(_kb_ok(), _market_ok())
        self.assertEqual(iren.verdict, "WAIT")
        self.assertEqual(gold.verdict, "WAIT")
        self.assertNotEqual(iren.verdict, "GO")

    def test_complete_calm_is_watch(self):
        iren = evaluate_attack_iren(
            _kb_ok(),
            _market_ok(),
            indicators=_complete_indicators(spike=False),
        )
        self.assertEqual(iren.verdict, "WATCH")
        self.assertNotEqual(iren.verdict, "GO")
        self.assertIn("phase2_watch", iren.reason)
        self.assertIn("sma20", iren.inputs_used)

    def test_volume_spike_without_chase_is_go_candidate(self):
        iren = evaluate_attack_iren(
            _kb_ok(),
            _market_ok(),
            indicators=_complete_indicators(spike=True),
        )
        self.assertEqual(iren.verdict, "GO_CANDIDATE")
        self.assertNotEqual(iren.verdict, "GO")
        self.assertIn("not_a_purchase_go", iren.reason)
        self.assertIn(iren.verdict, LIVE_VERDICTS)

    def test_sharp_move_is_alert_not_candidate(self):
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

    def test_live_path_never_emits_go(self):
        cases = [
            evaluate_attack_iren(_kb_ok(), _market_ok()),
            evaluate_attack_iren(_kb_ok(), _market_ok(), indicators=_complete_indicators(spike=True)),
            evaluate_defense_gold(_kb_ok(), _market_ok(), indicators=_complete_indicators()),
        ]
        for decision in cases:
            self.assertNotEqual(decision.verdict, "GO")
            self.assertNotEqual(decision.verdict, "EXIT")
            self.assertIn(decision.verdict, LIVE_VERDICTS)


class MailAndLogTests(unittest.TestCase):
    def test_watch_suppressed_go_candidate_would_send(self):
        self.assertEqual(dry_run("ATTACK #001", "WATCH"), MAIL_SUPPRESSED)
        self.assertEqual(dry_run("ATTACK #001", "GO_CANDIDATE"), MAIL_WOULD_SEND)

    def test_logstore_writes_required_fields(self):
        decision = evaluate_attack_iren(
            _kb_ok(),
            _market_ok(),
            indicators=_complete_indicators(spike=True),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_run([decision.to_dict()], log_dir=tmp, market=_market_ok())
            self.assertTrue(path.is_file())
            self.assertNotIn("AI-Knowledge", path.parts)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("date", document)
            row = document["decisions"][0]
            self.assertEqual(row["verdict"], "GO_CANDIDATE")
            self.assertIn("reason", row)
            self.assertIn("indicators", row)
            self.assertIn("missing", row)
            self.assertIn("inputs_used", row)
            self.assertEqual(row["market_summary"]["price"], 10.0)

    def test_logstore_rejects_knowledge_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            forbidden = Path(tmp) / "AI-Knowledge" / "logs"
            forbidden.mkdir(parents=True)
            with self.assertRaises(ValueError):
                write_run([], log_dir=forbidden)

    @patch("v2.engine.fetch_market", return_value=_market_ok())
    @patch("v2.engine.load_knowledge", return_value=_kb_ok())
    def test_engine_writes_log(self, *_mocks):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = run_phase1(log_dir=tmp)
            self.assertEqual(len(out), 2)
            self.assertTrue(any(Path(tmp).rglob("run-*.json")))
            self.assertIn("V2_LOG", buf.getvalue())
            self.assertNotEqual(out[0]["verdict"], "GO")


if __name__ == "__main__":
    unittest.main()
