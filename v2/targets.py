"""Watch identifiers only. Canonical text stays in AI-Knowledge.

Phase3-A: confirmed Test IDs only (ATTACK #001 / DEFENSE #001).
This module does not add tickers, issue GO, place orders, or write
to Watchlist / Performance / StrategyBank.
"""

ATTACK_001 = {
    "test_id": "ATTACK #001",
    "asset": "IREN",
    "market": "NASDAQ",
    "kind": "attack",
    "budget_jpy": 100000,
    "horizon": "6 months",
}

DEFENSE_001 = {
    "test_id": "DEFENSE #001",
    "asset": "SBI・iシェアーズ・ゴールドファンド（為替ヘッジあり）",
    "kind": "defense",
    "budget_jpy": 100000,
    "horizon": "3 years",
}

TARGETS = (ATTACK_001, DEFENSE_001)
CONFIRMED_TEST_IDS = (ATTACK_001["test_id"], DEFENSE_001["test_id"])

KB_FILES = (
    "Projects/Investment/Portfolio.md",
    "Projects/Investment/Watchlist.md",
    "Projects/Investment/StrategyBank.md",
    "Projects/Investment/DecisionEngine.md",
)


def is_confirmed_test_id(test_id: str) -> bool:
    """Read-only check. Does not register new Watchlist names."""
    return test_id in CONFIRMED_TEST_IDS
