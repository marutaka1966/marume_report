"""Confirmed Holdings name -> official issuer page. Do not invent codes."""

from __future__ import annotations

PARSER_MUFG = "mufg"
PARSER_PICTET = "pictet"
PARSER_SBI = "sbi"
PARSER_DAIWA = "daiwa"

# Exact Holdings.md names only. URLs are the issuer pages confirmed in research.
OFFICIAL_FUND_PAGES: dict[str, dict[str, str]] = {
    "eMAXIS Slim 米国株式（S&P500）": {
        "url": "https://emaxis.am.mufg.jp/fund/253266.html",
        "parser": PARSER_MUFG,
    },
    "iTrustインド株式": {
        "url": "https://www.pictet.co.jp/fund/iindia.html",
        "parser": PARSER_PICTET,
    },
    "SBI日本高配当株式（分配）ファンド（年4回決算型）": {
        "url": "https://apl.wealthadvisor.jp/webasp/sbi_am/pc/basic/sa_2023121201.html",
        "parser": PARSER_SBI,
    },
    "eMAXIS Slim 全世界株式（オール・カントリー）": {
        "url": "https://emaxis.am.mufg.jp/fund/253425.html",
        "parser": PARSER_MUFG,
    },
    "eMAXIS NASDAQ100インデックス": {
        "url": "https://www.am.mufg.jp/fund/254062.html",
        "parser": PARSER_MUFG,
    },
    "iFreeNEXT FANG+インデックス": {
        "url": "https://www.daiwa-am.co.jp/funds/detail/3346/detail_top.html",
        "parser": PARSER_DAIWA,
    },
}

# Official MUFG AM endpoint used by the confirmed product pages.
MUFG_FUND_DETAILS = "https://www.am.mufg.jp/mukamapi/fund_details/?fund_cd={fund_cd}"
