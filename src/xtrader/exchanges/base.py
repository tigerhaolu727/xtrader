"""Abstract exchange client definition."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import AsyncIterator, Iterable, Sequence

from xtrader.common.models import (
    AccountBalance,
    Candle,
    CandleInterval,
    ExchangeFeature,
    MarketMeta,
    MarketType,
    Position,
)


class ExchangeClient(ABC):
    """Interface that every exchange implementation must satisfy."""

    name: str
    features: ExchangeFeature

    # --- Discovery & metadata -------------------------------------------------
    @abstractmethod
    def list_markets(self, market_type: MarketType | None = None) -> Sequence[MarketMeta]:
        """Return known markets, optionally filtered by market type."""

    @abstractmethod
    def supports(self, feature: ExchangeFeature) -> bool:
        """Report whether the exchange exposes the provided feature bit."""

    # --- Account & risk -------------------------------------------------------
    @abstractmethod
    def get_account_balances(
        self,
        market_type: MarketType,
        assets: Iterable[str] | None = None,
    ) -> Sequence[AccountBalance]:
        """Fetch balances for the requested market/account scope."""

    @abstractmethod
    def get_positions(
        self,
        market_type: MarketType,
        symbols: Iterable[str] | None = None,
    ) -> Sequence[Position]:
        """Return current open positions, if the market type supports derivatives."""

    # --- Market data ----------------------------------------------------------
    @abstractmethod
    def fetch_klines(
        self,
        symbol: str,
        interval: CandleInterval,
        start_time: datetime,
        end_time: datetime | None = None,
        limit: int | None = None,
        market_type: MarketType | None = None,
    ) -> Sequence[Candle]:
        """Pull historical OHLCV bars."""

    @abstractmethod
    async def stream_klines(
        self,
        symbols: Sequence[str],
        interval: CandleInterval,
        market_type: MarketType | None = None,
    ) -> AsyncIterator[Candle]:
        """Yield live OHLCV updates as they arrive."""


__all__ = ["ExchangeClient"]
