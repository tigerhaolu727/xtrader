"""Market type enums shared across exchange adapters."""

from __future__ import annotations

from enum import Enum


class MarketType(str, Enum):
    """Supported market groupings across exchanges."""

    SPOT = "spot"
    LINEAR_SWAP = "linear_swap"
    INVERSE_SWAP = "inverse_swap"
    LINEAR_FUTURES = "linear_futures"
    INVERSE_FUTURES = "inverse_futures"


__all__ = ["MarketType"]
