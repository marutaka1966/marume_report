"""US regular-close collector tests. No live orders. No AI-Knowledge writes."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from v2 import DATA_UNAVAILABLE
from v2.collect_us import collect_us_regular_closes, write_us_closes
from v2.holdings import parse_us_tickers
from v2.market import SYMBOLS
from v2.us_closes import REQUIRED_FIELDS, collect_symbol
from v2.us_session import NY, last_completed_session_date, session_phase

HOLDINGS_SAMPLE = """
## 1. 保有数値

### 国内株

| 銘柄コード | 銘柄名 | 保有数量 |
|------------|--------|----------|
| 148A | ハッチ・ワーク | 200株 |

### 米国株

| 銘柄コード | 銘柄名 | 保有数量 | 平均取得価格 | 取得金額 | 現在株価 | 評価額 | 含み損益 |
|------------|--------|----------|--------------|----------|----------|--------|----------|
| IRDM | IRDM | 100株 | 未確認 | 未確認 | 未確認 | 未確認 |
| IREN | IREN | 16株 | 37.69 USD | 603.04 USD | 未確認 | 未確認 | 未確認 |
| PLTR | PLTR | 50株 | 未確認 | 未確認 | 未確認 | 未確認 | 未確認 |

### 投資信託

| 銘柄コード | 銘柄名 |
|------------|--------|
| 未確認 | eMAXIS Slim 米国株式（S&P500） |

## 2. 投資管理

### 米国株

| 銘柄コード | 銘柄名 |
|------------|--------|
| IREN | IREN |
"""

REAL_HOLDINGS = Path(
    "/Users/marumetakayuki/AI-Knowledge/Projects/Investment/Portfolio/Holdings.md"
)


def _ny(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=NY)


def _bars(*pairs: tuple[str, float]) -> dict:
    from datetime import date as date_cls

    bars = []
    for day_text, close in pairs:
        year, month, day = (int(part) for part in day_text.split("-"))
        bars.append({"date": date_cls(year, month, day), "close": close})
    return {"bars": bars, "currency": "USD", "source": "test://yahoo"}


class HoldingsParseTests(unittest.TestCase):
    def test_extracts_iren_and_ignores_japan_and_funds(self):
        tickers = parse_us_tickers(HOLDINGS_SAMPLE)
        self.assertIn("IREN", tickers)
        self.assertEqual(tickers, ["IRDM", "IREN", "PLTR"])
        self.assertNotIn("148A", tickers)
        self.assertNotIn("未確認", tickers)
        self.assertNotEqual(set(tickers), set(SYMBOLS))

    def test_real_holdings_includes_iren(self):
        if not REAL_HOLDINGS.is_file():
            self.skipTest("Holdings.md is not available locally")
        tickers = parse_us_tickers(REAL_HOLDINGS.read_text(encoding="utf-8"))
        self.assertIn("IREN", tickers)
        self.assertNotIn("148A", tickers)
        self.assertTrue(tickers)
        self.assertNotEqual(set(tickers), set(SYMBOLS))


class SessionDateTests(unittest.TestCase):
    def test_premarket_uses_previous_session(self):
        now = _ny(2026, 9, 3, 8, 0)
        self.assertEqual(session_phase(now), "pre_market")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-02")

    def test_regular_hours_uses_previous_session(self):
        now = _ny(2026, 9, 3, 12, 0)
        self.assertEqual(session_phase(now), "regular_open")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-02")

    def test_after_hours_uses_today_session(self):
        now = _ny(2026, 9, 3, 17, 0)
        self.assertEqual(session_phase(now), "after_hours")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-03")

    def test_weekend_uses_friday(self):
        now = _ny(2026, 9, 5, 12, 0)
        self.assertEqual(session_phase(now), "closed")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-09-04")

    def test_thanksgiving_uses_wednesday(self):
        now = _ny(2026, 11, 26, 12, 0)
        self.assertEqual(session_phase(now), "closed")
        self.assertEqual(last_completed_session_date(now).isoformat(), "2026-11-25")


class CloseSelectionTests(unittest.TestCase):
    def test_ignores_intraday_and_unfinished_today_bar(self):
        payload = _bars(("2026-09-02", 10.0), ("2026-09-03", 999.0))
        pre = collect_symbol("IREN", now=_ny(2026, 9, 3, 8, 0), fetch_bars=lambda _s: payload)
        rth = collect_symbol("IREN", now=_ny(2026, 9, 3, 12, 0), fetch_bars=lambda _s: payload)
        self.assertEqual(pre["price"], 10.0)
        self.assertEqual(pre["price_date"], "2026-09-02")
        self.assertEqual(rth["price"], 10.0)
        self.assertEqual(rth["price_date"], "2026-09-02")
        self.assertNotEqual(pre["price"], 999.0)

    def test_after_hours_uses_completed_daily_close_not_post_price(self):
        def fetch(_symbol: str) -> dict:
            data = _bars(("2026-09-02", 10.0), ("2026-09-03", 11.5))
            data["postMarketPrice"] = 12.34
            data["preMarketPrice"] = 9.0
            data["regularMarketPrice"] = 12.34
            return data

        row = collect_symbol("IREN", now=_ny(2026, 9, 3, 17, 0), fetch_bars=fetch)
        self.assertEqual(row["price"], 11.5)
        self.assertEqual(row["price_date"], "2026-09-03")
        self.assertEqual(row["session_status"], "regular_close_complete")

    def test_weekend_and_holiday_pick_last_completed_session(self):
        weekend = collect_symbol(
            "IREN",
            now=_ny(2026, 9, 5, 12, 0),
            fetch_bars=lambda _s: _bars(("2026-09-03", 10.0), ("2026-09-04", 11.0)),
        )
        holiday = collect_symbol(
            "IREN",
            now=_ny(2026, 11, 26, 12, 0),
            fetch_bars=lambda _s: _bars(("2026-11-25", 20.0), ("2026-11-26", 99.0)),
        )
        self.assertEqual(weekend["price_date"], "2026-09-04")
        self.assertEqual(weekend["price"], 11.0)
        self.assertEqual(holiday["price_date"], "2026-11-25")
        self.assertEqual(holiday["price"], 20.0)

    def test_missing_session_bar_is_unavailable_not_backfilled(self):
        row = collect_symbol(
            "IREN",
            now=_ny(2026, 9, 3, 17, 0),
            fetch_bars=lambda _s: _bars(("2026-09-02", 10.0)),
        )
        self.assertEqual(row["price"], DATA_UNAVAILABLE)
        self.assertEqual(row["price_date"], DATA_UNAVAILABLE)


class CollectorTests(unittest.TestCase):
    def test_does_not_use_fixed_symbol_list(self):
        source = inspect.getsource(collect_us_regular_closes)
        self.assertNotIn("SYMBOLS", source)
        self.assertNotIn("fetch_market", source)
        called: list[str] = []

        def fetch(symbol: str) -> dict:
            called.append(symbol)
            return _bars(("2026-09-03", 1.0))

        with tempfile.TemporaryDirectory() as tmp:
            collect_us_regular_closes(
                now=_ny(2026, 9, 3, 17, 0),
                log_dir=tmp,
                tickers=["ZZQQ", "IREN"],
                fetch_bars=fetch,
            )
        self.assertEqual(called, ["ZZQQ", "IREN"])
        self.assertNotIn("GOLD", called)
        self.assertNotIn("USDJPY", called)
        self.assertNotIn("US10Y", called)

    def test_one_failure_does_not_stop_others(self):
        def fetch(symbol: str):
            if symbol == "BAD":
                raise RuntimeError("network")
            return _bars(("2026-09-03", 5.0))

        with tempfile.TemporaryDirectory() as tmp:
            document = collect_us_regular_closes(
                now=_ny(2026, 9, 3, 17, 0),
                log_dir=tmp,
                tickers=["IREN", "BAD", "PLTR"],
                fetch_bars=fetch,
            )
        by_symbol = {row["symbol"]: row for row in document["quotes"]}
        self.assertEqual(by_symbol["IREN"]["price"], 5.0)
        self.assertEqual(by_symbol["PLTR"]["price"], 5.0)
        self.assertEqual(by_symbol["BAD"]["price"], DATA_UNAVAILABLE)
        self.assertEqual(len(document["quotes"]), 3)

    def test_required_metadata_on_every_record(self):
        def fetch(symbol: str):
            if symbol == "BAD":
                return None
            return _bars(("2026-09-03", 5.0))

        with tempfile.TemporaryDirectory() as tmp:
            document = collect_us_regular_closes(
                now=_ny(2026, 9, 3, 17, 0),
                log_dir=tmp,
                tickers=["IREN", "BAD"],
                fetch_bars=fetch,
            )
        for row in document["quotes"]:
            for field in REQUIRED_FIELDS:
                self.assertIn(field, row)
                self.assertIsNotNone(row[field])

    def test_rejects_ai_knowledge_log_path(self):
        with self.assertRaises(ValueError):
            write_us_closes(
                {"quotes": []},
                log_dir="/Users/marumetakayuki/AI-Knowledge",
            )


if __name__ == "__main__":
    unittest.main()
