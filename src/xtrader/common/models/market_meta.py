"""Market metadata models."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .market_type import MarketType


@dataclass(frozen=True, slots=True)
class MarketMeta:
    """Static description of a tradable market (symbol)."""

    symbol: str
    display_name: str
    market_type: MarketType
    base_asset: str
    quote_asset: str
    price_precision: int
    size_precision: int
    contract_value: Optional[Decimal] = None


__all__ = ["MarketMeta"]
