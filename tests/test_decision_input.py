"""Decision-input builder tests. No live orders. No AI-Knowledge writes."""

from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from v2 import DATA_UNAVAILABLE
from v2.collect_decision import collect_decision_input, finish_decision
from v2.collect_jp import collect_jp_regular_closes
from v2.decision_input import (
    CLASS_FUND,
    CLASS_JP,
    CLASS_US,
    FRESHNESS_UNKNOWN,
    FUND_FRESHNESS,
    FUND_FRESHNESS_BASIS,
    INCOMPLETE_SESSION,
    MISSING_LOG,
    MISSING_QUOTE,
    STALE_SESSION,
    STATUS_OK,
    STATUS_REVIEW,
    UNKNOWN_QUOTE_ERROR,
    _ready_asset,
    public_decision_summary,
    write_decision_input,
)
from v2.holdings import parse_fund_names, parse_jp_holding_rows, parse_jp_tickers, parse_us_holding_rows, parse_us_tickers
from v2.jp_session import TOKYO

HOLDINGS_SAMPLE = """
## 1. 保有数値

### 国内株

| 銘柄コード | 銘柄名 | 保有数量 | 平均取得価格 | 現在株価 | 評価額 | 含み損益 |
|------------|--------|----------|--------------|----------|--------|----------|
| 1111 | テスト工業A | 10株 | 未確認 | 未確認 | 未確認 | 未確認 |
| 2222 | テスト工業B | 20株 | 未確認 | 未確認 | 未確認 | 未確認 |

### 米国株

| 銘柄コード | 銘柄名 | 保有数量 | 平均取得価格 | 取得金額 | 現在株価 | 評価額 | 含み損益 |
|------------|--------|----------|--------------|----------|----------|--------|----------|
| TSTA | Test Asset A | 3株 | 12.34 USD | 37.02 USD | 未確認 | 未確認 | 未確認 |
| TSTB | Test Asset B | 4株 | 未確認 | 未確認 | 未確認 | 未確認 | 未確認 |

### 投資信託

| 銘柄コード | 銘柄名 | 保有数量 | 平均取得価格 | 現在株価 | 評価額 | 含み損益 |
|------------|--------|----------|--------------|----------|--------|----------|
| 未確認 | テスト投信A | 未確認 | 未確認 | 未確認 | 未確認 | 未確認 |
| 未確認 | テスト投信B | 未確認 | 未確認 | 未確認 | 未確認 | 未確認 |

## 2. 投資管理

### 投資信託

| 銘柄コード | 銘柄名 | 市場 |
|------------|--------|------|
| 未確認 | 管理表だけのテスト投信 | 投資信託 |
"""


def _tokyo(year: int, month: int, day: int, hour: int = 22) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=TOKYO)


def _write_log(log_dir: Path, name: str, document: dict) -> None:
    dest = log_dir / "2026-09-04"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / name).write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _jp_quote(symbol: str, price: float | str, day: str = "2026-09-04") -> dict:
    ok = price != DATA_UNAVAILABLE
    return {
        "symbol": symbol,
        "asset_type": "jp_equity",
        "price": price,
        "currency": "JPY" if ok else DATA_UNAVAILABLE,
        "price_date": day if ok else DATA_UNAVAILABLE,
        "observed_at": "2026-09-04T16:10:00+09:00",
        "source": "test://jp",
        "freshness_status": "complete_session" if ok else DATA_UNAVAILABLE,
        "session_status": "regular_close_complete" if ok else DATA_UNAVAILABLE,
        "error": None if ok else DATA_UNAVAILABLE,
    }


def _us_quote(symbol: str, price: float) -> dict:
    return {
        "symbol": symbol,
        "asset_type": "us_equity",
        "price": price,
        "currency": "USD",
        "price_date": "2026-09-04",
        "observed_at": "2026-09-05T07:00:00+09:00",
        "source": "test://us",
        "freshness_status": "complete_session",
        "session_status": "regular_close_complete",
    }


def _fund_quote(name: str, nav: float) -> dict:
    return {
        "name": name,
        "asset_type": "investment_trust",
        "nav": nav,
        "currency": "JPY",
        "price_date": "2026-09-04",
        "observed_at": "2026-09-04T21:00:00+09:00",
        "source": "test://fund",
        "freshness_status": FUND_FRESHNESS,
        "freshness_basis": FUND_FRESHNESS_BASIS,
        "status": "ok",
        "error": None,
    }


class HoldingsRowTests(unittest.TestCase):
    def test_copies_confirmed_qty_and_cost_only(self):
        jp = parse_jp_holding_rows(HOLDINGS_SAMPLE)
        us = parse_us_holding_rows(HOLDINGS_SAMPLE)
        self.assertEqual([row["symbol"] for row in jp], ["1111", "2222"])
        self.assertEqual(jp[0]["quantity"], "10株")
        self.assertEqual(jp[0]["avg_cost"], DATA_UNAVAILABLE)
        self.assertEqual(us[0]["quantity"], "3株")
        self.assertEqual(us[0]["avg_cost"], "12.34 USD")
        self.assertEqual(us[0]["cost_amount"], "37.02 USD")
        self.assertEqual(us[1]["avg_cost"], DATA_UNAVAILABLE)
        self.assertEqual(parse_jp_tickers(HOLDINGS_SAMPLE), ["1111", "2222"])
        self.assertEqual(parse_us_tickers(HOLDINGS_SAMPLE), ["TSTA", "TSTB"])
        self.assertEqual(parse_fund_names(HOLDINGS_SAMPLE), ["テスト投信A", "テスト投信B"])


class DecisionInputTests(unittest.TestCase):
    def test_ready_asset_rechecks_equity_date_and_exact_freshness(self):
        row = {
            "asset_class": CLASS_JP,
            "price": 100.0,
            "currency": "JPY",
            "price_date": "2026-09-04",
            "observed_at": "2026-09-04T16:10:00+09:00",
            "source": "test://jp",
            "freshness_status": "stale",
            "freshness_basis": "target_completed_session",
            "collection_status": STATUS_OK,
            "usability_status": STATUS_OK,
        }
        self.assertFalse(_ready_asset(row, expected_session_date="2026-09-04"))
        row["freshness_status"] = "complete_session"
        self.assertFalse(_ready_asset(row, expected_session_date="2026-09-03"))
        self.assertTrue(_ready_asset(row, expected_session_date="2026-09-04"))

    def test_merges_latest_logs_without_fx_or_guesses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_log(
                root,
                "jp-closes-1.json",
                {
                    "log_kind": "jp_regular_closes",
                    "quotes": [_jp_quote("1111", 100.0), _jp_quote("2222", DATA_UNAVAILABLE)],
                },
            )
            _write_log(
                root,
                "us-closes-1.json",
                {"log_kind": "us_regular_closes", "quotes": [_us_quote("TSTA", 10.0), _us_quote("TSTB", 20.0)]},
            )
            _write_log(
                root,
                "fund-nav-1.json",
                {
                    "log_kind": "fund_official_navs",
                    "quotes": [
                        _fund_quote("テスト投信A", 12345.0),
                        _fund_quote("テスト投信B", 23456.0),
                    ],
                },
            )
            from v2.holdings import parse_fund_holding_rows, parse_jp_holding_rows, parse_us_holding_rows

            document = collect_decision_input(
                now=_tokyo(2026, 9, 5, 22),
                log_dir=root,
                holdings={
                    "jp": parse_jp_holding_rows(HOLDINGS_SAMPLE),
                    "us": parse_us_holding_rows(HOLDINGS_SAMPLE),
                    "funds": parse_fund_holding_rows(HOLDINGS_SAMPLE),
                },
            )
            by_id = {(row["asset_class"], row["symbol"], row["name"]): row for row in document["assets"]}
            jp_ok = by_id[(CLASS_JP, "1111", DATA_UNAVAILABLE)]
            jp_bad = by_id[(CLASS_JP, "2222", DATA_UNAVAILABLE)]
            us_asset = by_id[(CLASS_US, "TSTA", DATA_UNAVAILABLE)]
            fund = by_id[(CLASS_FUND, DATA_UNAVAILABLE, "テスト投信A")]
            self.assertEqual(jp_ok["price"], 100.0)
            self.assertEqual(jp_ok["currency"], "JPY")
            self.assertEqual(jp_ok["quantity"], "10株")
            self.assertEqual(jp_ok["collection_status"], STATUS_OK)
            self.assertEqual(jp_bad["collection_status"], UNKNOWN_QUOTE_ERROR)
            self.assertEqual(us_asset["avg_cost"], "12.34 USD")
            self.assertEqual(us_asset["cost_amount"], "37.02 USD")
            self.assertEqual(us_asset["currency"], "USD")
            self.assertEqual(fund["price"], 12345.0)
            self.assertEqual(fund["quantity"], DATA_UNAVAILABLE)
            self.assertNotIn("usd_jpy", document)
            self.assertNotIn("converted", json.dumps(document))
            self.assertEqual(document["summary"]["jp_ok"], 1)
            self.assertEqual(document["summary"]["jp_failed"], 1)
            self.assertEqual(document["summary"]["us_ok"], 2)
            self.assertEqual(document["summary"]["funds_ok"], 2)
            self.assertEqual(document["summary"]["price_fetch_succeeded"], 5)
            self.assertEqual(document["summary"]["decision_usable"], 5)
            self.assertEqual(document["summary"]["missing"], 0)
            self.assertEqual(document["summary"]["decision_status"], STATUS_REVIEW)
            self.assertTrue(Path(document["log_path"]).is_file())
            self.assertTrue(Path(document["log_path"]).with_suffix(".md").is_file())
            payload = public_decision_summary(document)
            dumped = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("1111", dumped)
            self.assertNotIn("TSTA", dumped)
            self.assertNotIn("12.34", dumped)
            self.assertNotIn("テスト工業", dumped)
            self.assertNotIn("12345", dumped)

    def test_stale_session_and_missing_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_log(
                root,
                "jp-closes-1.json",
                {"log_kind": "jp_regular_closes", "quotes": [_jp_quote("1111", 100.0, day="2026-09-03")]},
            )
            from v2.holdings import parse_jp_holding_rows

            document = collect_decision_input(
                now=_tokyo(2026, 9, 5, 22),
                log_dir=root,
                holdings={"jp": parse_jp_holding_rows(HOLDINGS_SAMPLE), "us": [], "funds": []},
                write_markdown=False,
            )
            by_symbol = {row["symbol"]: row for row in document["assets"] if row["asset_class"] == CLASS_JP}
            self.assertEqual(by_symbol["1111"]["collection_status"], STATUS_OK)
            self.assertEqual(by_symbol["1111"]["usability_status"], STALE_SESSION)
            self.assertEqual(by_symbol["1111"]["price"], DATA_UNAVAILABLE)
            self.assertEqual(by_symbol["2222"]["collection_status"], MISSING_QUOTE)
            self.assertEqual(document["summary"]["missing"], 1)

    def test_equity_requires_exact_freshness_and_completed_session(self):
        holding = {
            "symbol": "1111",
            "name": DATA_UNAVAILABLE,
            "quantity": "10株",
            "avg_cost": DATA_UNAVAILABLE,
            "cost_amount": DATA_UNAVAILABLE,
        }
        cases = (
            ("stale", "regular_close_complete", FRESHNESS_UNKNOWN),
            ("complete_session", "regular_open", INCOMPLETE_SESSION),
        )
        for freshness, session_status, expected in cases:
            with self.subTest(freshness=freshness, session_status=session_status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                quote = _jp_quote("1111", 100.0)
                quote["freshness_status"] = freshness
                quote["session_status"] = session_status
                _write_log(root, "jp-closes-1.json", {"log_kind": "jp_regular_closes", "quotes": [quote]})
                document = collect_decision_input(
                    now=_tokyo(2026, 9, 5, 22),
                    log_dir=root,
                    holdings={"jp": [holding], "us": [], "funds": []},
                    write_markdown=False,
                )
                row = document["assets"][0]
                self.assertEqual(row["collection_status"], STATUS_OK)
                self.assertEqual(row["usability_status"], expected)
                self.assertEqual(row["price"], DATA_UNAVAILABLE)
                self.assertEqual(document["summary"]["price_fetch_succeeded"], 1)
                self.assertEqual(document["summary"]["decision_usable"], 0)
                self.assertEqual(document["summary"]["decision_status"], STATUS_REVIEW)

    def test_fund_requires_official_latest_evidence(self):
        holding = {
            "symbol": DATA_UNAVAILABLE,
            "name": "テスト投信A",
            "quantity": DATA_UNAVAILABLE,
            "avg_cost": DATA_UNAVAILABLE,
            "cost_amount": DATA_UNAVAILABLE,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quote = _fund_quote("テスト投信A", 12345.0)
            quote.pop("freshness_status")
            quote.pop("freshness_basis")
            _write_log(root, "fund-nav-1.json", {"log_kind": "fund_official_navs", "quotes": [quote]})
            document = collect_decision_input(
                now=_tokyo(2026, 9, 5, 22),
                log_dir=root,
                holdings={"jp": [], "us": [], "funds": [holding]},
                write_markdown=False,
            )
            row = document["assets"][0]
            self.assertEqual(row["collection_status"], STATUS_OK)
            self.assertEqual(row["usability_status"], FRESHNESS_UNKNOWN)
            self.assertEqual(row["price"], DATA_UNAVAILABLE)
            self.assertEqual(document["summary"]["price_fetch_succeeded"], 1)
            self.assertEqual(document["summary"]["decision_usable"], 0)

    def test_unknown_quote_error_is_sanitized(self):
        holding = {
            "symbol": "1111",
            "name": DATA_UNAVAILABLE,
            "quantity": DATA_UNAVAILABLE,
            "avg_cost": DATA_UNAVAILABLE,
            "cost_amount": DATA_UNAVAILABLE,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quote = _jp_quote("1111", DATA_UNAVAILABLE)
            quote["error"] = "failed for 1111 at https://secret.example/quote"
            _write_log(root, "jp-closes-1.json", {"log_kind": "jp_regular_closes", "quotes": [quote]})
            document = collect_decision_input(
                now=_tokyo(2026, 9, 5, 22),
                log_dir=root,
                holdings={"jp": [holding], "us": [], "funds": []},
                write_markdown=False,
            )
            row = document["assets"][0]
            self.assertEqual(row["collection_status"], UNKNOWN_QUOTE_ERROR)
            payload = public_decision_summary(document)
            dumped = json.dumps(payload)
            self.assertIn(UNKNOWN_QUOTE_ERROR, dumped)
            self.assertNotIn("1111", dumped)
            self.assertNotIn("secret.example", dumped)

    def test_missing_log_is_classified(self):
        with tempfile.TemporaryDirectory() as tmp:
            from v2.holdings import parse_us_holding_rows

            document = collect_decision_input(
                now=_tokyo(2026, 9, 5, 22),
                log_dir=tmp,
                holdings={"jp": [], "us": parse_us_holding_rows(HOLDINGS_SAMPLE), "funds": []},
                write_markdown=False,
            )
            self.assertTrue(all(row["collection_status"] == MISSING_LOG for row in document["assets"]))
            self.assertEqual(document["summary"]["missing"], 2)

    def test_rejects_ai_knowledge_log_path(self):
        with self.assertRaises(ValueError):
            write_decision_input({"assets": []}, log_dir="/Users/marumetakayuki/AI-Knowledge")

    def test_does_not_call_live_collectors(self):
        source = inspect.getsource(collect_decision_input)
        self.assertNotIn("collect_jp_regular_closes", source)
        self.assertNotIn("collect_us_regular_closes", source)
        self.assertNotIn("collect_fund_navs", source)
        self.assertNotIn("launchd", inspect.getsource(collect_jp_regular_closes))

    def test_finish_decision_hides_identifiers(self):
        document = {
            "holdings_error": None,
            "summary": {
                "jp_ok": 1,
                "jp_failed": 0,
                "us_ok": 0,
                "us_failed": 0,
                "funds_ok": 0,
                "funds_failed": 0,
                "missing": 0,
                "decision_status": STATUS_REVIEW,
            },
            "assets": [
                {
                    "asset_class": CLASS_JP,
                    "symbol": "1111",
                    "name": DATA_UNAVAILABLE,
                    "quantity": "10株",
                    "avg_cost": DATA_UNAVAILABLE,
                    "cost_amount": DATA_UNAVAILABLE,
                    "price": 100.0,
                    "currency": "JPY",
                    "price_date": "2026-09-04",
                    "observed_at": "2026-09-04T16:10:00+09:00",
                    "source": "secret://url",
                    "freshness_status": "complete_session",
                    "freshness_basis": "target_completed_session",
                    "collection_status": STATUS_OK,
                    "usability_status": STATUS_OK,
                }
            ],
        }
        with patch("sys.stdout", new_callable=StringIO) as stdout:
            code = finish_decision(document)
        printed = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertNotIn("1111", printed)
        self.assertNotIn("10株", printed)
        self.assertNotIn("100.0", printed)
        self.assertNotIn("secret://url", printed)


if __name__ == "__main__":
    unittest.main()
