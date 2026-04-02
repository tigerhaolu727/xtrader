"""Exchange capability bit flags."""

from __future__ import annotations

from enum import IntFlag


class ExchangeFeature(IntFlag):
    """Feature switches to express exchange-specific capabilities."""

    ACCOUNTS = 1 << 0
    POSITIONS = 1 << 1
    HISTORICAL_KLINES = 1 << 2
    REALTIME_KLINES = 1 << 3
    SPOT = 1 << 4
    DERIVATIVES = 1 << 5


__all__ = ["ExchangeFeature"]
