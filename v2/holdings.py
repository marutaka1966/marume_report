"""Read Holdings.md as Read Only. Never write. Never invent tickers."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from v2 import DATA_UNAVAILABLE

DEFAULT_REPO = "marutaka1966/AI-Knowledge"
HOLDINGS_FILE = "Projects/Investment/Portfolio/Holdings.md"
JP_SECTION = "### 国内株"
US_SECTION = "### 米国株"
FUND_SECTION = "### 投資信託"
HOLDINGS_NUMERIC = "## 1. 保有数値"


def load_holdings_markdown() -> tuple[str | None, str | None]:
    """Return (markdown, error). error is DATA_UNAVAILABLE when unread."""
    root = os.environ.get("AI_KNOWLEDGE_PATH", "").strip()
    if root:
        path = Path(root) / HOLDINGS_FILE
        if not path.is_file():
            return None, DATA_UNAVAILABLE
        return path.read_text(encoding="utf-8"), None
    token = (
        os.environ.get("AI_KNOWLEDGE_TOKEN", "").strip()
        or os.environ.get("GITHUB_TOKEN", "").strip()
    )
    if not token:
        return None, DATA_UNAVAILABLE
    return _from_github(token)


def parse_jp_tickers(markdown: str) -> list[str]:
    """Tickers from the first 国内株 table under 保有数値. US stocks and funds are ignored."""
    return _parse_codes(_numeric_table(markdown, JP_SECTION))


def parse_us_tickers(markdown: str) -> list[str]:
    """Tickers from the first 米国株 table under 保有数値. JP stocks and funds are ignored."""
    return _parse_codes(_numeric_table(markdown, US_SECTION))


def parse_fund_names(markdown: str) -> list[str]:
    """Fund names from the first 投資信託 table under 保有数値.

    Codes stay unread. JP and US ticker tables are ignored.
    """
    return _parse_names(_numeric_table(markdown, FUND_SECTION))


def load_jp_tickers() -> tuple[list[str], str | None]:
    text, error = load_holdings_markdown()
    if error or not text:
        return [], error or DATA_UNAVAILABLE
    return parse_jp_tickers(text), None


def load_us_tickers() -> tuple[list[str], str | None]:
    text, error = load_holdings_markdown()
    if error or not text:
        return [], error or DATA_UNAVAILABLE
    return parse_us_tickers(text), None


def load_fund_names() -> tuple[list[str], str | None]:
    text, error = load_holdings_markdown()
    if error or not text:
        return [], error or DATA_UNAVAILABLE
    return parse_fund_names(text), None


def _parse_codes(table: str) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    for line in table.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        code = cells[0]
        if not code or code == "銘柄コード" or set(code) <= {"-", ":"}:
            continue
        if code == "未確認":
            continue
        if code in seen:
            continue
        seen.add(code)
        tickers.append(code)
    return tickers


def _parse_names(table: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for line in table.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = cells[1]
        if not name or name == "銘柄名" or set(name) <= {"-", ":"}:
            continue
        if name == "未確認":
            continue
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _numeric_table(markdown: str, heading: str) -> str:
    numeric = markdown
    start_numeric = markdown.find(HOLDINGS_NUMERIC)
    if start_numeric >= 0:
        numeric = markdown[start_numeric:]
    start = numeric.find(heading)
    if start < 0:
        return ""
    rest = numeric[start + len(heading) :]
    next_heading = rest.find("\n### ")
    if next_heading >= 0:
        rest = rest[:next_heading]
    return rest


def _from_github(token: str) -> tuple[str | None, str | None]:
    repo = os.environ.get("AI_KNOWLEDGE_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO
    url = f"https://api.github.com/repos/{repo}/contents/{HOLDINGS_FILE}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "marume-report-v2",
        },
    )
    if req.get_method() != "GET":
        return None, DATA_UNAVAILABLE
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None, DATA_UNAVAILABLE
    content = payload.get("content")
    if not content:
        return None, DATA_UNAVAILABLE
    try:
        return base64.b64decode(content).decode("utf-8"), None
    except (ValueError, UnicodeDecodeError):
        return None, DATA_UNAVAILABLE
