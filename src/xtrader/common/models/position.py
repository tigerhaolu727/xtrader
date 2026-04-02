"""Position models for derivatives trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .market_type import MarketType
from .position_side import PositionSide


@dataclass(frozen=True, slots=True)
class Position:
    """Open position information for derivatives accounts."""

    symbol: str
    market_type: MarketType
    side: PositionSide
    size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    leverage: Optional[Decimal]
    unrealized_pnl: Decimal
    timestamp: datetime


__all__ = ["Position"]
