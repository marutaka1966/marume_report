"""Pure price/volume indicators. Missing series stay None; no filler values."""

from __future__ import annotations


def sma(closes: list[float], window: int = 20) -> float | None:
    if window <= 0 or len(closes) < window:
        return None
    sample = closes[-window:]
    if any(value is None for value in sample):
        return None
    return sum(sample) / window


def rsi(closes: list[float], period: int = 14) -> float | None:
    if period <= 0 or len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    start = len(closes) - (period + 1)
    for index in range(start + 1, start + 1 + period):
        delta = closes[index] - closes[index - 1]
        if delta > 0:
            gains += delta
        else:
            losses += -delta
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def volume_spike(
    volumes: list[float],
    window: int = 20,
    multiple: float = 2.0,
) -> bool | None:
    if window <= 0 or multiple <= 0 or len(volumes) < window + 1:
        return None
    previous = volumes[-(window + 1) : -1]
    last = volumes[-1]
    if last is None or any(value is None for value in previous):
        return None
    average = sum(previous) / window
    if average <= 0:
        return None
    return last >= average * multiple


def from_quote(quote: dict | None) -> dict | None:
    """Build indicator payload from a market quote. None if no close series."""
    if not quote or quote.get("error"):
        return None
    closes = [close for close in (quote.get("closes") or []) if close is not None]
    volumes = [volume for volume in (quote.get("volumes") or []) if volume is not None]
    if not closes:
        return None
    return {
        "sma20": sma(closes, 20),
        "rsi14": rsi(closes, 14),
        "volume_spike": volume_spike(volumes, 20, 2.0),
    }
