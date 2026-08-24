"""Watch identifiers only. Canonical text stays in AI-Knowledge."""

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

KB_FILES = (
    "Projects/Investment/Portfolio.md",
    "Projects/Investment/Watchlist.md",
    "Projects/Investment/StrategyBank.md",
    "Projects/Investment/DecisionEngine.md",
)
