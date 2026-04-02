"""OHLCV candle models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .candle_interval import CandleInterval
from .market_type import MarketType


@dataclass(frozen=True, slots=True)
class Candle:
    """Normalized OHLCV candle."""

    symbol: str
    market_type: MarketType
    interval: CandleInterval
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Optional[Decimal] = None


__all__ = ["Candle"]
