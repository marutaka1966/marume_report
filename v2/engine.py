"""V2 Phase 3-A dry-run. Watchlist read + decision-history log.

Does not send mail, place orders, or write to AI-Knowledge.
Entry point: python -m v2.engine
Daily Marume Report continues to use main.py unchanged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from v2 import LIVE_VERDICTS
from v2.evaluate import evaluate_attack_iren, evaluate_defense_gold
from v2.indicators import from_quote
from v2.knowledge import load_knowledge
from v2.logstore import write_run
from v2.mail_gate import dry_run
from v2.market import fetch_market
from v2.schema import Decision, InvalidVerdictError, require_valid_verdict
from v2.targets import ATTACK_001, DEFENSE_001, is_confirmed_test_id


def run_phase1(
    *,
    kb=None,
    market: dict | None = None,
    decisions: list[Decision] | None = None,
    log_dir: str | Path | bool | None = "logs",
) -> list[dict]:
    live = decisions is None
    market_for_log = market
    if live:
        kb = load_knowledge() if kb is None else kb
        market = fetch_market() if market is None else market
        market_for_log = market
        decisions = _evaluate_confirmed(kb, market)

    payloads = []
    for decision in decisions:
        if live:
            _forbid_live_go(decision)
        else:
            try:
                require_valid_verdict(decision.verdict)
            except InvalidVerdictError:
                decision.verdict = "WAIT"
                decision.reason = ["INVALID_VERDICT", *list(decision.reason)]
                decision.confidence = 0
        payload = decision.to_dict()
        payloads.append(payload)
        print(json.dumps(payload, ensure_ascii=False))
        dry_run(decision.test_id, decision.verdict, strict=True)
    if log_dir:
        path = write_run(payloads, log_dir=log_dir, market=market_for_log)
        print(f"V2_LOG {path}")
    return payloads


def _evaluate_confirmed(kb, market: dict) -> list[Decision]:
    """Evaluate Watchlist-confirmed IDs only. Does not add names to Watchlist."""
    decisions: list[Decision] = []
    if is_confirmed_test_id(ATTACK_001["test_id"]):
        decisions.append(
            evaluate_attack_iren(kb, market, indicators=from_quote(market.get("IREN")))
        )
    if is_confirmed_test_id(DEFENSE_001["test_id"]):
        decisions.append(
            evaluate_defense_gold(kb, market, indicators=from_quote(market.get("GOLD")))
        )
    return decisions


def _forbid_live_go(decision: Decision) -> None:
    if decision.verdict in LIVE_VERDICTS:
        return
    decision.verdict = "WAIT"
    decision.reason = ["LIVE_GO_FORBIDDEN", *list(decision.reason)]
    decision.confidence = 0


def main() -> int:
    run_phase1(log_dir="logs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
