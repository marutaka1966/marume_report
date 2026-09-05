"""TSE regular-close collector tests. No live orders. No AI-Knowledge writes."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from v2 import DATA_UNAVAILABLE
from v2.collect_jp import collect_jp_regular_closes, write_jp_closes
from v2.collect_us import collect_us_regular_closes
from v2.holdings import parse_jp_tickers, parse_us_tickers
from v2.jp_closes import REQUIRED_FIELDS, collect_symbol, yahoo_symbol
from v2.jp_session import TOKYO, last_completed_session_date, session_phase
from v2.market import SYMBOLS

HOLDINGS_SAMPLE = """
## 1. 保有数値

### 国内株

| 銘柄コード | 銘柄名 | 保有数量 |
|------------|--------|----------|
| 1111 | テスト工業A | 10株 |
| 2222 | テスト工業B | 20株 |

### 米国株

| 銘柄コード | 銘柄名 | 保有数量 |
|------------|--------|----------|
| TSTA | Test Asset A | 3株 |

### 投資信託

| 銘柄コード | 銘柄名 |
|------------|--------|
| 未確認 | テスト投信A |

## 2. 投資管理

### 国内株

| 銘柄コード | 銘柄名 |
|------------|--------|
| 1111 | テスト工業A |
"""

REAL_HOLDINGS = Path(
    "/Users/marumetakayuki/AI-Knowledge/Projects/Investment/Portfolio/Holdings.md"
)


def _tokyo(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TOKYO)


def _bars(*pairs: tuple[str, float]) -> dict:
    from datetime import date as date_cls

    bars = []
    for day_text, close in pairs:
        year, month, day = (int(part) for part in day_text.split("-"))
        bars.append({"date": date_cls(year, month, day), "close": close})
    return {"bars": bars, "currency": "JPY", "source": "test://yahoo"}


class HoldingsParseTests(unittest.TestCase):
    def test_extracts_jp_and_ignores_us_and_funds(self):
        tickers = parse_jp_tickers(HOLDINGS_SAMPLE)
        self.assertEqual(tickers, ["1111", "2222"])
        self.assertNotIn("TSTA", tickers)
        self.assertNotIn("未確認", tickers)
        self.assertEqual(parse_us_tickers(HOLDINGS_SAMPLE), ["TSTA"])

    def test_real_holdings_parse_without_identifier_assumptions(self):
        if not REAL_HOLDINGS.is_file():
            self.skipTest("Holdings.md is not available locally")
        tickers = parse_jp_tickers(REAL_HOLDINGS.read_text(encoding="utf-8"))
        self.assertTrue(tickers)
        self.assertTrue(all(isinstance(ticker, str) and ticker for ticker in tickers))
        self.assertNotIn("未確認", tickers)


class SessionDateTests(unittest.TestCase):
    def test_premarket_uses_previous_session(self):
        now = _tokyo(2026, 9, 3, 8, 0)
        self.assertEqual(session_phase(now), "pre_market")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-02")

    def test_morning_session_uses_previous_session(self):
        now = _tokyo(2026, 9, 3, 10, 0)
        self.assertEqual(session_phase(now), "regular_open")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-02")

    def test_lunch_uses_previous_session(self):
        now = _tokyo(2026, 9, 3, 12, 0)
        self.assertEqual(session_phase(now), "regular_open")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-02")

    def test_before_close_auction_uses_previous_session(self):
        now = _tokyo(2026, 9, 3, 15, 20)
        self.assertEqual(session_phase(now), "regular_open")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-02")

    def test_after_close_uses_today_session(self):
        now = _tokyo(2026, 9, 3, 15, 30)
        self.assertEqual(session_phase(now), "after_hours")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-03")

    def test_weekend_uses_friday(self):
        now = _tokyo(2026, 9, 5, 12, 0)
        self.assertEqual(session_phase(now), "closed")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-04")

    def test_marine_day_uses_previous_friday(self):
        now = _tokyo(2026, 9, 21, 12, 0)
        self.assertEqual(session_phase(now), "closed")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-18")


class CloseSelectionTests(unittest.TestCase):
    def test_yahoo_symbol_appends_tse_suffix(self):
        self.assertEqual(yahoo_symbol("1111"), "1111.T")
        self.assertEqual(yahoo_symbol("2222.T"), "2222.T")

    def test_ignores_intraday_and_unfinished_today_bar(self):
        payload = _bars(("2026-09-02", 100.0), ("2026-09-03", 999.0))
        pre = collect_symbol("1111", now=_tokyo(2026, 9, 3, 8, 0), fetch_bars=lambda _s: payload)
        rth = collect_symbol("1111", now=_tokyo(2026, 9, 3, 10, 0), fetch_bars=lambda _s: payload)
        self.assertEqual(pre["price"], 100.0)
        self.assertEqual(pre["price_date"], "2026-09-02")
        self.assertEqual(rth["price"], 100.0)
        self.assertNotEqual(pre["price"], 999.0)
        self.assertEqual(pre["currency"], "JPY")
        self.assertEqual(pre["asset_type"], "jp_equity")

    def test_after_hours_uses_completed_daily_close_not_live_price(self):
        def fetch(_symbol: str) -> dict:
            data = _bars(("2026-09-02", 100.0), ("2026-09-03", 110.0))
            data["regularMarketPrice"] = 111.0
            data["preMarketPrice"] = 90.0
            data["postMarketPrice"] = 112.0
            return data

        row = collect_symbol("2222", now=_tokyo(2026, 9, 3, 16, 0), fetch_bars=fetch)
        self.assertEqual(row["price"], 110.0)
        self.assertEqual(row["price_date"], "2026-09-03")
        self.assertEqual(row["session_status"], "regular_close_complete")

    def test_weekend_and_holiday_pick_last_completed_session(self):
        weekend = collect_symbol(
            "2222",
            now=_tokyo(2026, 9, 5, 12, 0),
            fetch_bars=lambda _s: _bars(("2026-09-03", 10.0), ("2026-09-04", 11.0)),
        )
        holiday = collect_symbol(
            "2222",
            now=_tokyo(2026, 9, 21, 12, 0),
            fetch_bars=lambda _s: _bars(("2026-09-18", 20.0), ("2026-09-21", 99.0)),
        )
        self.assertEqual(weekend["price_date"], "2026-09-04")
        self.assertEqual(weekend["price"], 11.0)
        self.assertEqual(holiday["price_date"], "2026-09-18")
        self.assertEqual(holiday["price"], 20.0)

    def test_missing_session_bar_is_unavailable_not_backfilled(self):
        row = collect_symbol(
            "2222",
            now=_tokyo(2026, 9, 3, 16, 0),
            fetch_bars=lambda _s: _bars(("2026-09-02", 10.0)),
        )
        self.assertEqual(row["price"], DATA_UNAVAILABLE)
        self.assertEqual(row["price_date"], DATA_UNAVAILABLE)


class CollectorTests(unittest.TestCase):
    def test_does_not_use_us_fixed_symbol_list(self):
        source = inspect.getsource(collect_jp_regular_closes)
        self.assertNotIn("SYMBOLS", source)
        self.assertNotIn("fetch_market", source)
        called: list[str] = []

        def fetch(symbol: str) -> dict:
            called.append(symbol)
            return _bars(("2026-09-03", 1.0))

        with tempfile.TemporaryDirectory() as tmp:
            collect_jp_regular_closes(
                now=_tokyo(2026, 9, 3, 16, 0),
                log_dir=tmp,
                tickers=["1111", "2222"],
                fetch_bars=fetch,
            )
        self.assertEqual(called, ["1111", "2222"])
        self.assertNotIn("TSTA", called)
        self.assertNotIn("GOLD", called)
        self.assertNotEqual(set(called), set(SYMBOLS))

    def test_one_failure_does_not_stop_others(self):
        def fetch(symbol: str):
            if symbol == "BAD":
                raise RuntimeError("network")
            return _bars(("2026-09-03", 5.0))

        with tempfile.TemporaryDirectory() as tmp:
            document = collect_jp_regular_closes(
                now=_tokyo(2026, 9, 3, 16, 0),
                log_dir=tmp,
                tickers=["1111", "BAD", "2222"],
                fetch_bars=fetch,
            )
        by_symbol = {row["symbol"]: row for row in document["quotes"]}
        self.assertEqual(by_symbol["1111"]["price"], 5.0)
        self.assertEqual(by_symbol["2222"]["price"], 5.0)
        self.assertEqual(by_symbol["BAD"]["price"], DATA_UNAVAILABLE)
        self.assertEqual(len(document["quotes"]), 3)

    def test_required_metadata_on_every_record(self):
        def fetch(symbol: str):
            if symbol == "BAD":
                return None
            return _bars(("2026-09-03", 5.0))

        with tempfile.TemporaryDirectory() as tmp:
            document = collect_jp_regular_closes(
                now=_tokyo(2026, 9, 3, 16, 0),
                log_dir=tmp,
                tickers=["1111", "BAD"],
                fetch_bars=fetch,
            )
        for row in document["quotes"]:
            for field in REQUIRED_FIELDS:
                self.assertIn(field, row)
                self.assertIsNotNone(row[field])

    def test_skips_duplicate_save_for_complete_session(self):
        called: list[str] = []

        def fetch(symbol: str) -> dict:
            called.append(symbol)
            return _bars(("2026-09-03", 5.0))

        with tempfile.TemporaryDirectory() as tmp:
            first = collect_jp_regular_closes(
                now=_tokyo(2026, 9, 3, 16, 10),
                log_dir=tmp,
                tickers=["1111", "2222"],
                fetch_bars=fetch,
            )
            self.assertFalse(first.get("reused_log"))
            self.assertEqual(called, ["1111", "2222"])
            files = list(Path(tmp).rglob("jp-closes-*.json"))
            self.assertEqual(len(files), 1)
            called.clear()
            second = collect_jp_regular_closes(
                now=_tokyo(2026, 9, 3, 16, 10),
                log_dir=tmp,
                tickers=["1111", "2222"],
                fetch_bars=fetch,
            )
            self.assertEqual(called, [])
            self.assertTrue(second.get("reused_log"))
            self.assertEqual(len(list(Path(tmp).rglob("jp-closes-*.json"))), 1)

    def test_rewrites_when_previous_session_log_is_incomplete(self):
        def fetch(symbol: str):
            if symbol == "BAD":
                raise RuntimeError("network")
            return _bars(("2026-09-03", 5.0))

        called: list[str] = []

        def fetch_ok(symbol: str) -> dict:
            called.append(symbol)
            return _bars(("2026-09-03", 5.0))

        with tempfile.TemporaryDirectory() as tmp:
            collect_jp_regular_closes(
                now=_tokyo(2026, 9, 3, 16, 10),
                log_dir=tmp,
                tickers=["1111", "BAD"],
                fetch_bars=fetch,
            )
            second = collect_jp_regular_closes(
                now=_tokyo(2026, 9, 3, 16, 10),
                log_dir=tmp,
                tickers=["1111"],
                fetch_bars=fetch_ok,
            )
            self.assertFalse(second.get("reused_log"))
            self.assertEqual(called, ["1111"])

    def test_rejects_ai_knowledge_log_path(self):
        with self.assertRaises(ValueError):
            write_jp_closes(
                {"quotes": []},
                log_dir="/Users/marumetakayuki/AI-Knowledge",
            )

    def test_us_collector_still_ignores_jp_tickers(self):
        called: list[str] = []

        def fetch(symbol: str) -> dict:
            called.append(symbol)
            return {
                "bars": [],
                "currency": "USD",
                "source": "test://yahoo",
            }

        with tempfile.TemporaryDirectory() as tmp:
            collect_us_regular_closes(
                now=datetime(2026, 9, 3, 17, 0, tzinfo=TOKYO),
                log_dir=tmp,
                tickers=["TSTA"],
                fetch_bars=fetch,
            )
        self.assertEqual(called, ["TSTA"])
        self.assertNotIn("1111", called)


if __name__ == "__main__":
    unittest.main()
