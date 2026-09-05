"""Official fund NAV collector tests. No live orders. No AI-Knowledge writes."""

from __future__ import annotations

import inspect
import json
import re
import tempfile
import unittest
import urllib.error
from datetime import datetime
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

from v2 import DATA_UNAVAILABLE
from v2.collect_funds import collect_fund_navs, write_fund_navs
from v2.collect_jp import collect_jp_regular_closes
from v2.collect_report import public_summary
from v2.collect_us import collect_us_regular_closes
from v2.fund_fetch import BLOCKED_BY_SOURCE
from v2.fund_nav import (
    ERR_AMBIGUOUS_DATE,
    ERR_HTML,
    ERR_MISSING_DATE,
    ERR_MISSING_NAV,
    ERR_UNMAPPED,
    REQUIRED_FIELDS,
    collect_fund,
    parse_daiwa_html,
    parse_mufg_details,
    parse_pictet_html,
    parse_sbi_html,
)
from v2.fund_sources import OFFICIAL_FUND_PAGES
from v2.holdings import parse_fund_names, parse_jp_tickers, parse_us_tickers
from v2.jp_session import TOKYO
from v2.market import SYMBOLS

HOLDINGS_SAMPLE = """
## 1. 保有数値

### 国内株

| 銘柄コード | 銘柄名 | 保有数量 |
|------------|--------|----------|
| 1111 | テスト工業A | 10株 |

### 米国株

| 銘柄コード | 銘柄名 | 保有数量 |
|------------|--------|----------|
| TSTA | Test Asset A | 3株 |

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

REAL_HOLDINGS = Path(
    "/Users/marumetakayuki/AI-Knowledge/Projects/Investment/Portfolio/Holdings.md"
)

EXPECTED_FUNDS = [
    "eMAXIS Slim 米国株式（S&P500）",
    "iTrustインド株式",
    "SBI日本高配当株式（分配）ファンド（年4回決算型）",
    "eMAXIS Slim 全世界株式（オール・カントリー）",
    "eMAXIS NASDAQ100インデックス",
    "iFreeNEXT FANG+インデックス",
]

MUFG_HTML = """
<input type="hidden" id="js-fund-code" value="253266">
<p><span class="js-base-date">基準日</span>：<span class="js-date"></span></p>
<th>基準価額</th>
<span class="js-base-price"></span><span>円</span>
"""

MUFG_JSON = {
    "result": {"status": 200},
    "datasets": {
        "cfm_base_date": "20260903",
        "cfm_base_price": 44779,
    },
}

PICTET_HTML = """
<div class="cmp-funds__fund-summary table-responsive">
<table class="table">
<thead>
<tr>
<th scope="col"><h3>基本情報</h3></th>
<th scope="col" class="cmp-fund__fund-summary-value"><small>基準日: 2026年09月03日</small></th>
</tr>
</thead>
<tbody>
<tr>
<td class='cmp-fund__fund-summary-key'>基準価額</td>
<td class='cmp-fund__fund-summary-value'>23,352円</td>
</tr>
</tbody>
</table>
</div>
"""

DAIWA_HTML = """
<div class="p-fundDetail__info">
  <h2>運用情報</h2>
  <p class="__time">基準日：<time class="date" datetime="2026-09-03">2026/09/03</time></p>
  <table>
    <tr>
      <th>基準価額</th>
      <td>
        <p><span class="text-[19px]">99,198</span>円</p>
      </td>
    </tr>
  </table>
</div>
"""

DAIWA_HTML_NO_DATE = """
<div class="p-fundDetail__info">
  <h2>運用情報</h2>
  <p class="__time">基準日：<time class="date" datetime=""></time></p>
  <table>
    <tr>
      <th>基準価額</th>
      <td>
        <p><span>99,198</span>円</p>
      </td>
    </tr>
  </table>
</div>
"""

SBI_HTML_NAV_AND_HYOKA = """
<table class="tpdt mb30">
<tr>
<th>基準価額</th>
<th>前日比</th>
<th>純資産総額</th>
<th>カテゴリー</th>
</tr>
<tr>
<td><span class="fprice">17,792</span>円</td>
<td>78円</td>
<td>235,764百万円</td>
<td>国内中型バリュー</td>
</tr>
<tr>
<td><span class="ptdate">2026年09月03日</span></td>
<td>&nbsp;</td>
<td>&nbsp;</td>
<td><span class="ptdate">評価基準日 2026年07月31日</span></td>
</tr>
</table>
"""

SBI_HTML_TWO_NAV_DATES = """
<table class="tpdt mb30">
<tr>
<th>基準価額</th>
<th>カテゴリー</th>
</tr>
<tr>
<td><span class="fprice">17,792</span>円</td>
<td>国内中型バリュー</td>
</tr>
<tr>
<td><span class="ptdate">2026年09月03日</span> <span class="ptdate">2026年09月02日</span></td>
<td><span class="ptdate">評価基準日 2026年07月31日</span></td>
</tr>
</table>
"""

SBI_HTML_NAV_NO_DATE = """
<table class="tpdt mb30">
<tr>
<th>基準価額</th>
<th>カテゴリー</th>
</tr>
<tr>
<td><span class="fprice">17,792</span>円</td>
<td>国内中型バリュー</td>
</tr>
<tr>
<td>&nbsp;</td>
<td><span class="ptdate">評価基準日 2026年07月31日</span></td>
</tr>
</table>
"""

SBI_HTML_LABELED = """
<table class="tpdt mb30">
<tr>
<th>基準価額</th>
</tr>
<tr>
<td><span class="fprice">17,792</span>円</td>
</tr>
<tr>
<td>基準日：2026年09月03日</td>
</tr>
</table>
"""


def _tokyo(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=TOKYO)


class HoldingsParseTests(unittest.TestCase):
    def test_extracts_fund_names_and_ignores_equities(self):
        names = parse_fund_names(HOLDINGS_SAMPLE)
        self.assertEqual(names, ["テスト投信A", "テスト投信B"])
        self.assertNotIn("テスト工業A", names)
        self.assertNotIn("TSTA", names)
        self.assertNotIn("未確認", names)
        self.assertNotIn("管理表だけのテスト投信", names)
        self.assertEqual(parse_jp_tickers(HOLDINGS_SAMPLE), ["1111"])
        self.assertEqual(parse_us_tickers(HOLDINGS_SAMPLE), ["TSTA"])

    def test_real_holdings_parse_without_identifier_assumptions(self):
        if not REAL_HOLDINGS.is_file():
            self.skipTest("Holdings.md is not available locally")
        names = parse_fund_names(REAL_HOLDINGS.read_text(encoding="utf-8"))
        self.assertTrue(names)
        self.assertTrue(all(isinstance(name, str) and name for name in names))
        self.assertNotIn("未確認", names)


class ParseRuleTests(unittest.TestCase):
    def test_mufg_json_requires_nav_and_date(self):
        nav, price_date, error = parse_mufg_details(MUFG_JSON)
        self.assertEqual(nav, 44779.0)
        self.assertEqual(price_date, "2026-09-03")
        self.assertIsNone(error)
        missing_date = dict(MUFG_JSON)
        missing_date["datasets"] = {"cfm_base_price": 1, "cfm_base_date": ""}
        self.assertEqual(parse_mufg_details(missing_date)[2], ERR_MISSING_DATE)
        missing_nav = dict(MUFG_JSON)
        missing_nav["datasets"] = {"cfm_base_price": None, "cfm_base_date": "20260903"}
        self.assertEqual(parse_mufg_details(missing_nav)[2], ERR_MISSING_NAV)
        self.assertIsNotNone(parse_mufg_details({"hello": "world"})[2])

    def test_pictet_html_reads_summary_table(self):
        nav, price_date, error = parse_pictet_html(PICTET_HTML)
        self.assertEqual(nav, 23352.0)
        self.assertEqual(price_date, "2026-09-03")
        self.assertIsNone(error)

    def test_daiwa_missing_date_is_unavailable(self):
        nav, price_date, error = parse_daiwa_html(DAIWA_HTML)
        self.assertEqual(nav, 99198.0)
        self.assertEqual(price_date, "2026-09-03")
        self.assertIsNone(error)
        self.assertEqual(parse_daiwa_html(DAIWA_HTML_NO_DATE)[2], ERR_MISSING_DATE)

    def test_sbi_uses_nav_column_date_not_hyoka(self):
        nav, price_date, error = parse_sbi_html(SBI_HTML_NAV_AND_HYOKA)
        self.assertEqual(nav, 17792.0)
        self.assertEqual(price_date, "2026-09-03")
        self.assertIsNone(error)
        nav, price_date, error = parse_sbi_html(SBI_HTML_LABELED)
        self.assertEqual(nav, 17792.0)
        self.assertEqual(price_date, "2026-09-03")
        self.assertIsNone(error)
        self.assertEqual(parse_sbi_html(SBI_HTML_TWO_NAV_DATES)[2], ERR_AMBIGUOUS_DATE)
        self.assertEqual(parse_sbi_html(SBI_HTML_NAV_NO_DATE)[2], ERR_MISSING_DATE)

    def test_html_change_is_unavailable(self):
        self.assertEqual(parse_pictet_html("<html>no table</html>")[2], ERR_HTML)
        self.assertEqual(parse_daiwa_html("<html>no info</html>")[2], ERR_HTML)


class CollectorTests(unittest.TestCase):
    def test_ok_only_when_nav_and_date_present(self):
        row = collect_fund(
            "iTrustインド株式",
            now=_tokyo(2026, 9, 4),
            fetch_page=lambda _url: PICTET_HTML,
        )
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["nav"], 23352.0)
        self.assertEqual(row["price_date"], "2026-09-03")
        self.assertEqual(row["currency"], "JPY")
        self.assertEqual(row["freshness_status"], "latest_official_published")
        self.assertEqual(row["freshness_basis"], "official_current_value")
        self.assertIsNone(row["error"])
        self.assertEqual(row["source"], OFFICIAL_FUND_PAGES["iTrustインド株式"]["url"])

    def test_daiwa_missing_date_record(self):
        row = collect_fund(
            "iFreeNEXT FANG+インデックス",
            now=_tokyo(2026, 9, 4),
            fetch_page=lambda _url: DAIWA_HTML_NO_DATE,
        )
        self.assertEqual(row["status"], DATA_UNAVAILABLE)
        self.assertEqual(row["nav"], DATA_UNAVAILABLE)
        self.assertEqual(row["price_date"], DATA_UNAVAILABLE)
        self.assertEqual(row["freshness_status"], DATA_UNAVAILABLE)
        self.assertEqual(row["freshness_basis"], DATA_UNAVAILABLE)
        self.assertEqual(row["error"], ERR_MISSING_DATE)

    def test_sbi_nav_column_record(self):
        row = collect_fund(
            "SBI日本高配当株式（分配）ファンド（年4回決算型）",
            now=_tokyo(2026, 9, 4),
            fetch_page=lambda _url: SBI_HTML_NAV_AND_HYOKA,
        )
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["nav"], 17792.0)
        self.assertEqual(row["price_date"], "2026-09-03")
        self.assertIsNone(row["error"])
        missing = collect_fund(
            "SBI日本高配当株式（分配）ファンド（年4回決算型）",
            now=_tokyo(2026, 9, 4),
            fetch_page=lambda _url: SBI_HTML_NAV_NO_DATE,
        )
        self.assertEqual(missing["status"], DATA_UNAVAILABLE)
        self.assertEqual(missing["error"], ERR_MISSING_DATE)
        self.assertEqual(missing["nav"], DATA_UNAVAILABLE)
        self.assertEqual(missing["price_date"], DATA_UNAVAILABLE)

    def test_mufg_uses_official_api_without_html(self):
        row = collect_fund(
            "eMAXIS Slim 米国株式（S&P500）",
            now=_tokyo(2026, 9, 4),
            fetch_page=lambda _url: None,
            fetch_details=lambda _url: MUFG_JSON,
        )
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["nav"], 44779.0)
        self.assertEqual(row["price_date"], "2026-09-03")
        self.assertIn("mukamapi/fund_details", row["source"])
        self.assertIn("253266", row["source"])

    def test_source_block_is_classified(self):
        def forbidden(_url: str) -> str:
            raise urllib.error.HTTPError(
                "https://example.invalid",
                403,
                "Forbidden",
                EmailMessage(),
                BytesIO(),
            )

        row = collect_fund(
            "iTrustインド株式",
            now=_tokyo(2026, 9, 4),
            fetch_page=forbidden,
        )
        self.assertEqual(row["status"], DATA_UNAVAILABLE)
        self.assertEqual(row["error"], BLOCKED_BY_SOURCE)
        self.assertNotIn("example.invalid", row["error"])
        self.assertNotIn("iTrust", row["error"])

    def test_unmapped_name_is_unavailable(self):
        row = collect_fund("存在しないファンド", now=_tokyo(2026, 9, 4))
        self.assertEqual(row["status"], DATA_UNAVAILABLE)
        self.assertEqual(row["error"], ERR_UNMAPPED)
        self.assertEqual(row["source"], DATA_UNAVAILABLE)

    def test_one_failure_does_not_stop_others(self):
        def fetch_page(url: str) -> str | None:
            if "pictet" in url:
                raise RuntimeError("network")
            if "daiwa" in url:
                return DAIWA_HTML
            if "wealthadvisor" in url:
                return SBI_HTML_NAV_AND_HYOKA
            match = re.search(r"/fund/(\d+)\.html", url)
            if match:
                return f'<input type="hidden" id="js-fund-code" value="{match.group(1)}">'
            return MUFG_HTML

        def fetch_details(_url: str) -> dict:
            return MUFG_JSON

        with tempfile.TemporaryDirectory() as tmp:
            document = collect_fund_navs(
                now=_tokyo(2026, 9, 4),
                log_dir=tmp,
                names=EXPECTED_FUNDS,
                fetch_page=fetch_page,
                fetch_details=fetch_details,
            )
            by_name = {row["name"]: row for row in document["quotes"]}
            self.assertEqual(len(document["quotes"]), 6)
            self.assertEqual(by_name["eMAXIS Slim 米国株式（S&P500）"]["status"], "ok")
            self.assertEqual(by_name["eMAXIS Slim 全世界株式（オール・カントリー）"]["status"], "ok")
            self.assertEqual(by_name["eMAXIS NASDAQ100インデックス"]["status"], "ok")
            self.assertEqual(by_name["iFreeNEXT FANG+インデックス"]["status"], "ok")
            self.assertEqual(by_name["iTrustインド株式"]["status"], DATA_UNAVAILABLE)
            self.assertEqual(by_name["iTrustインド株式"]["error"], "UNKNOWN_FETCH_ERROR")
            self.assertEqual(
                by_name["SBI日本高配当株式（分配）ファンド（年4回決算型）"]["status"],
                "ok",
            )
            self.assertEqual(
                by_name["SBI日本高配当株式（分配）ファンド（年4回決算型）"]["price_date"],
                "2026-09-03",
            )
            payload = public_summary("funds", document)
            dumped = json.dumps(payload, ensure_ascii=False)
            self.assertEqual(payload["ok"], 5)
            self.assertEqual(payload["failed"], 1)
            self.assertEqual(payload["reasons"], [{"reason": "UNKNOWN_FETCH_ERROR", "count": 1}])
            for fund_name in EXPECTED_FUNDS:
                self.assertNotIn(fund_name, dumped)
            self.assertNotIn("pictet", dumped)
            self.assertNotIn("wealthadvisor", dumped)
            self.assertNotIn("23352", dumped)
            self.assertTrue(Path(document["log_path"]).is_file())
            saved = json.loads(Path(document["log_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["log_kind"], "fund_official_navs")
            self.assertEqual(len(saved["quotes"]), 6)

    def test_required_metadata_on_every_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            document = collect_fund_navs(
                now=_tokyo(2026, 9, 4),
                log_dir=tmp,
                names=["iTrustインド株式", "存在しないファンド"],
                fetch_page=lambda _url: PICTET_HTML,
            )
        for row in document["quotes"]:
            for field in REQUIRED_FIELDS:
                self.assertIn(field, row)

    def test_rejects_ai_knowledge_log_path(self):
        with self.assertRaises(ValueError):
            write_fund_navs(
                {"quotes": []},
                log_dir="/Users/marumetakayuki/AI-Knowledge",
            )

    def test_does_not_use_us_fixed_symbol_list(self):
        source = inspect.getsource(collect_fund_navs)
        self.assertNotIn("SYMBOLS", source)
        self.assertNotIn("fetch_market", source)
        self.assertNotEqual(set(EXPECTED_FUNDS), set(SYMBOLS))

    def test_equity_collectors_still_ignore_funds(self):
        jp_called: list[str] = []
        us_called: list[str] = []

        def jp_fetch(symbol: str) -> dict:
            jp_called.append(symbol)
            return {"bars": [], "currency": "JPY", "source": "test://yahoo"}

        def us_fetch(symbol: str) -> dict:
            us_called.append(symbol)
            return {"bars": [], "currency": "USD", "source": "test://yahoo"}

        with tempfile.TemporaryDirectory() as tmp:
            collect_jp_regular_closes(
                now=_tokyo(2026, 9, 4, 16),
                log_dir=tmp,
                tickers=["1111"],
                fetch_bars=jp_fetch,
            )
            collect_us_regular_closes(
                now=_tokyo(2026, 9, 4, 16),
                log_dir=tmp,
                tickers=["TSTA"],
                fetch_bars=us_fetch,
            )
        self.assertEqual(jp_called, ["1111"])
        self.assertEqual(us_called, ["TSTA"])
        self.assertNotIn("eMAXIS Slim 米国株式（S&P500）", jp_called)
        self.assertNotIn("eMAXIS Slim 米国株式（S&P500）", us_called)


if __name__ == "__main__":
    unittest.main()
