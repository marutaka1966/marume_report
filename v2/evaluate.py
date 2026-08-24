"""Conservative evaluator. Never fabricates GO. Unknown → WAIT."""

from __future__ import annotations

from v2 import DATA_UNAVAILABLE, LIVE_VERDICTS
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


def evaluate_attack_iren(kb, market: dict, indicators: dict | None = None) -> Decision:
    target = ATTACK_001
    reasons: list[str] = []
    risks: list[str] = ["do_not_chase", "high_risk_test_capital_only"]
    missing = _missing_kb(kb) + _missing_quote(market.get("IREN"), "IREN")
    watch = kb.text("Projects/Investment/Watchlist.md") if kb.available else ""
    if kb.available and "ATTACK #001" not in watch and "IREN" not in watch:
        missing.append("watchlist_iren")

    iren = market.get("IREN") or {}
    sharp_move = False
    if iren.get("price") is not None:
        reasons.append(f"IREN_price={iren['price']}")
        if iren.get("change_pct") is not None:
            reasons.append(f"IREN_change_pct={round(iren['change_pct'], 2)}")
            if abs(iren["change_pct"]) >= 8:
                risks.append("sharp_move")
                sharp_move = True
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

    _append_indicator_reasons(reasons, indicators)

    verdict = _phase2_verdict(
        missing=missing,
        indicators=indicators,
        sharp_move=sharp_move,
    )
    return _decision(
        target=target,
        verdict=verdict,
        confidence=0 if missing else 40,
        reason=_reason_prefix(verdict, indicators, reasons, missing),
        risks=risks,
        go_conditions=[
            "ChatGPT GO for date and limit price",
            "do_not_chase",
        ],
        invalidation_conditions=["investment_thesis_break", "dilution_exceeds_thesis"],
        indicators=indicators,
        missing=missing,
        inputs_used=_inputs_used(kb, market, indicators, ("IREN", "US10Y")),
    )


def evaluate_defense_gold(kb, market: dict, indicators: dict | None = None) -> Decision:
    target = DEFENSE_001
    reasons: list[str] = []
    risks: list[str] = ["avoid_chase_after_spike"]
    missing = _missing_kb(kb) + _missing_quote(market.get("GOLD"), "GOLD")
    watch = kb.text("Projects/Investment/Watchlist.md") if kb.available else ""
    if kb.available and "DEFENSE #001" not in watch and "ゴールドファンド" not in watch:
        missing.append("watchlist_gold")

    gold = market.get("GOLD") or {}
    sharp_move = False
    if gold.get("price") is not None:
        reasons.append(f"gold_price={gold['price']}")
        if gold.get("change_pct") is not None:
            reasons.append(f"gold_change_pct={round(gold['change_pct'], 2)}")
            if gold["change_pct"] >= 2:
                risks.append("possible_short_term_overheat")
                reasons.append("spike_wait_allowed")
                sharp_move = True
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

    _append_indicator_reasons(reasons, indicators)

    verdict = _phase2_verdict(
        missing=missing,
        indicators=indicators,
        sharp_move=sharp_move,
    )
    return _decision(
        target=target,
        verdict=verdict,
        confidence=0 if missing else 40,
        reason=_reason_prefix(verdict, indicators, reasons, missing),
        risks=risks,
        go_conditions=[
            "ChatGPT GO for timing",
            "lump_or_split_decided_at_go",
            "no_chase_after_spike",
        ],
        invalidation_conditions=["thesis_break", "hedge_role_invalid"],
        indicators=indicators,
        missing=missing,
        inputs_used=_inputs_used(kb, market, indicators, ("GOLD", "USDJPY")),
    )


def _phase2_verdict(
    *,
    missing: list[str],
    indicators: dict | None,
    sharp_move: bool,
) -> str:
    if missing:
        return "WAIT"
    if indicators is None:
        return "WAIT"
    spike = indicators.get("volume_spike")
    complete = indicators.get("sma20") is not None and indicators.get("rsi14") is not None
    if sharp_move:
        return "ALERT"
    if spike is True and complete:
        return "GO_CANDIDATE"
    return "WATCH"


def _cap_live(verdict: str) -> str:
    if verdict in LIVE_VERDICTS:
        return verdict
    return "WAIT"


def _decision(
    *,
    target: dict,
    verdict: str,
    confidence: int,
    reason: list[str],
    risks: list[str],
    go_conditions: list[str],
    invalidation_conditions: list[str],
    indicators: dict | None,
    missing: list[str],
    inputs_used: list[str],
) -> Decision:
    capped = _cap_live(verdict)
    if capped != verdict:
        reason = ["LIVE_GO_FORBIDDEN", *reason]
    return Decision(
        test_id=target["test_id"],
        asset=target["asset"],
        verdict=capped,
        confidence=confidence,
        reason=reason,
        risks=risks,
        go_conditions=go_conditions,
        invalidation_conditions=invalidation_conditions,
        entry_price=None,
        do_not_chase_above=None,
        indicators=dict(indicators or {}),
        missing=list(missing),
        inputs_used=inputs_used,
    )


def _reason_prefix(
    verdict: str,
    indicators: dict | None,
    reasons: list[str],
    missing: list[str],
) -> list[str]:
    prefix = ["chatgpt_owns_entry_go"]
    if missing:
        prefix = [DATA_UNAVAILABLE, *missing, *prefix]
    if indicators is None:
        prefix = ["phase1_no_auto_go", *prefix]
        if verdict == "WAIT" and not missing:
            prefix.append("important_fields_unconfirmed")
    elif verdict == "WATCH":
        prefix.append("phase2_watch")
    elif verdict == "ALERT":
        prefix.append("phase2_alert")
    elif verdict == "GO_CANDIDATE":
        prefix.append("phase2_go_candidate")
        prefix.append("not_a_purchase_go")
    elif verdict == "WAIT":
        prefix.append("phase2_wait")
    return [*prefix, *reasons]


def _append_indicator_reasons(reasons: list[str], indicators: dict | None) -> None:
    if not indicators:
        return
    for key in ("sma20", "rsi14", "volume_spike"):
        value = indicators.get(key)
        if value is None:
            reasons.append(f"{key}=unavailable")
        else:
            reasons.append(f"{key}={value}")


def _inputs_used(kb, market: dict, indicators: dict | None, quote_keys: tuple[str, ...]) -> list[str]:
    used: list[str] = []
    if getattr(kb, "available", False):
        used.append("ai_knowledge")
    for key in quote_keys:
        quote = market.get(key) or {}
        if quote.get("price") is not None:
            used.append(f"{key}_quote")
    if indicators:
        for key, value in indicators.items():
            if value is not None:
                used.append(key)
    return used


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
