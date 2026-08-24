"""Market quotes. Missing data stays unavailable; no filler prices."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from v2 import DATA_UNAVAILABLE

# 3mo daily bars: enough for SMA(20) and RSI(14). Do not invent missing bars.
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"

# Gold fund NAV ticker is unconfirmed in AI-Knowledge. Gold price uses futures.
SYMBOLS = {
    "IREN": "IREN",
    "GOLD": "GC=F",
    "USDJPY": "JPY=X",
    "US10Y": "^TNX",
}


def fetch_quote(symbol: str) -> dict | None:
    url = YAHOO_CHART.format(symbol=symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "marume-report-v2"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    try:
        result = data["chart"]["result"][0]
        meta = result["meta"]
        quote = result["indicators"]["quote"][0]
        closes = [c for c in (quote.get("close") or []) if c is not None]
        volumes = [v for v in (quote.get("volume") or []) if v is not None]
        price = meta.get("regularMarketPrice")
        if price is None and closes:
            price = closes[-1]
        change_pct = None
        if len(closes) >= 2 and closes[-2]:
            change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100
        return {
            "symbol": symbol,
            "price": price,
            "change_pct": change_pct,
            "volume": volumes[-1] if volumes else None,
            "closes": closes,
            "volumes": volumes,
        }
    except (KeyError, IndexError, TypeError):
        return None


def fetch_market() -> dict:
    out: dict = {}
    for key, symbol in SYMBOLS.items():
        quote = fetch_quote(symbol)
        out[key] = quote if quote and quote.get("price") is not None else {
            "error": DATA_UNAVAILABLE,
            "symbol": symbol,
        }
    return out
