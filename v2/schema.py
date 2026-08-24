from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from v2 import VALID_VERDICTS


class InvalidVerdictError(ValueError):
    pass


def require_valid_verdict(verdict: str) -> str:
    """Strict check. Unknown labels are errors, never coerced to GO."""
    if verdict not in VALID_VERDICTS:
        raise InvalidVerdictError(f"invalid verdict: {verdict!r}")
    return verdict


def safe_verdict(verdict: str) -> str:
    """Safety remap for Decision construction.

    Invalid labels become WAIT only. This must never map to GO, ALERT, or EXIT.
    Callers that need a hard failure should use require_valid_verdict().
    """
    if verdict in VALID_VERDICTS:
        return verdict
    return "WAIT"


@dataclass
class Decision:
    """Structured V2 verdict. Live evaluators must not emit a fabricated GO."""

    test_id: str
    asset: str
    verdict: str
    confidence: int
    reason: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    go_conditions: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    entry_price: float | None = None
    do_not_chase_above: float | None = None
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.now(timezone.utc).isoformat()
        # Safety: garbage in → WAIT. Never upgrade an invalid label to GO.
        self.verdict = safe_verdict(self.verdict)
        if self.confidence < 0:
            self.confidence = 0
        if self.confidence > 100:
            self.confidence = 100

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
