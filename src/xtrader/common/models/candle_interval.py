"""Candle interval enum models."""

from __future__ import annotations

from enum import Enum


class CandleInterval(str, Enum):
    """Canonical candle intervals used when requesting OHLCV data."""

    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"


__all__ = ["CandleInterval"]
