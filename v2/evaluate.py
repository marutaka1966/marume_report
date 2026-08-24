"""Conservative evaluator. Never fabricates GO. Unknown → WAIT."""

from __future__ import annotations

from v2 import DATA_UNAVAILABLE
from v2.schema import Decision
from v2.targets import ATTACK_001, DEFENSE_001, KB_FILES

IREN_CHECKS = (
    "latest_price",
    "volume_spike",
    "ai_cloud_arr",
    "customer_contracts",
    "gpu_deployment",
    "data_center_capacity",
    "earnings_guidance",
    "financing",
    "dilution",
    "us_rates",
    "ai_sector_sentiment",
)

GOLD_CHECKS = (
    "gold_price",
    "us_real_rates",
    "fed_outlook",
    "usdjpy",
    "geopolitics",
    "short_term_overheat",
    "equity_stress",
)


def evaluate_attack_iren(kb, market: dict) -> Decision:
    target = ATTACK_001
    reasons: list[str] = []
    risks: list[str] = ["do_not_chase", "high_risk_test_capital_only"]
    missing = _missing_kb(kb) + _missing_quote(market.get("IREN"), "IREN")
    watch = kb.text("Projects/Investment/Watchlist.md") if kb.available else ""
    if kb.available and "ATTACK #001" not in watch and "IREN" not in watch:
        missing.append("watchlist_iren")

    iren = market.get("IREN") or {}
    if iren.get("price") is not None:
        reasons.append(f"IREN_price={iren['price']}")
        if iren.get("change_pct") is not None:
            reasons.append(f"IREN_change_pct={round(iren['change_pct'], 2)}")
            if abs(iren["change_pct"]) >= 8:
                risks.append("sharp_move")
        if iren.get("volume") is not None:
            reasons.append(f"IREN_volume={iren['volume']}")
    else:
        reasons.append("IREN_price=unavailable")

    for item in IREN_CHECKS:
        if item in ("latest_price", "volume_spike", "us_rates"):
            continue
        reasons.append(f"{item}=not_confirmed")

    rates = market.get("US10Y") or {}
    if rates.get("price") is not None:
        reasons.append(f"US10Y={rates['price']}")
    else:
        missing.append("us_rates")

    if missing:
        return Decision(
            test_id=target["test_id"],
            asset=target["asset"],
            verdict="WAIT",
            confidence=0,
            reason=[DATA_UNAVAILABLE, *missing],
            risks=risks,
            go_conditions=[
                "ChatGPT GO for date and limit price",
                "do_not_chase",
            ],
            invalidation_conditions=["investment_thesis_break", "dilution_exceeds_thesis"],
            entry_price=None,
            do_not_chase_above=None,
        )

    return Decision(
        test_id=target["test_id"],
        asset=target["asset"],
        verdict="WAIT",
        confidence=40,
        reason=[
            "phase1_no_auto_go",
            "chatgpt_owns_entry_go",
            "important_fields_unconfirmed",
            *reasons,
        ],
        risks=risks,
        go_conditions=[
            "ChatGPT GO for date and limit price",
            "do_not_chase",
        ],
        invalidation_conditions=["investment_thesis_break", "dilution_exceeds_thesis"],
        entry_price=None,
        do_not_chase_above=None,
    )


def evaluate_defense_gold(kb, market: dict) -> Decision:
    target = DEFENSE_001
    reasons: list[str] = []
    risks: list[str] = ["avoid_chase_after_spike"]
    missing = _missing_kb(kb) + _missing_quote(market.get("GOLD"), "GOLD")
    watch = kb.text("Projects/Investment/Watchlist.md") if kb.available else ""
    if kb.available and "DEFENSE #001" not in watch and "ゴールドファンド" not in watch:
        missing.append("watchlist_gold")

    gold = market.get("GOLD") or {}
    if gold.get("price") is not None:
        reasons.append(f"gold_price={gold['price']}")
        if gold.get("change_pct") is not None:
            reasons.append(f"gold_change_pct={round(gold['change_pct'], 2)}")
            if gold["change_pct"] >= 2:
                risks.append("possible_short_term_overheat")
                reasons.append("spike_wait_allowed")
    else:
        reasons.append("gold_price=unavailable")

    fx = market.get("USDJPY") or {}
    if fx.get("price") is not None:
        reasons.append(f"USDJPY={fx['price']}")
    else:
        missing.append("USDJPY")

    for item in GOLD_CHECKS:
        if item in ("gold_price", "usdjpy", "short_term_overheat"):
            continue
        reasons.append(f"{item}=not_confirmed")

    if missing:
        return Decision(
            test_id=target["test_id"],
            asset=target["asset"],
            verdict="WAIT",
            confidence=0,
            reason=[DATA_UNAVAILABLE, *missing],
            risks=risks,
            go_conditions=[
                "ChatGPT GO for timing",
                "lump_or_split_decided_at_go",
                "no_chase_after_spike",
            ],
            invalidation_conditions=["thesis_break", "hedge_role_invalid"],
            entry_price=None,
            do_not_chase_above=None,
        )

    return Decision(
        test_id=target["test_id"],
        asset=target["asset"],
        verdict="WAIT",
        confidence=40,
        reason=[
            "phase1_no_auto_go",
            "chatgpt_owns_entry_go",
            "no_perfect_bottom_required",
            *reasons,
        ],
        risks=risks,
        go_conditions=[
            "ChatGPT GO for timing",
            "lump_or_split_decided_at_go",
            "no_chase_after_spike",
        ],
        invalidation_conditions=["thesis_break", "hedge_role_invalid"],
        entry_price=None,
        do_not_chase_above=None,
    )


def _missing_kb(kb) -> list[str]:
    if not kb.available:
        return [DATA_UNAVAILABLE]
    missing = []
    for path in KB_FILES:
        if not kb.text(path).strip():
            missing.append(path)
    return missing


def _missing_quote(quote: dict | None, label: str) -> list[str]:
    if not quote or quote.get("error") or quote.get("price") is None:
        return [f"{label}_quote"]
    return []
