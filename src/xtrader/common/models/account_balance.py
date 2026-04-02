"""Account balance snapshot models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .market_type import MarketType


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Snapshot of an account balance for a given asset/market type."""

    asset: str
    total: Decimal
    available: Decimal
    market_type: MarketType
    timestamp: datetime


__all__ = ["AccountBalance"]
