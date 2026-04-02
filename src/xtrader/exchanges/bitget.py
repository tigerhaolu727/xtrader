"""Bitget exchange implementation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Sequence

import httpx
from typing_extensions import Self

from xtrader.common.models import (
    AccountBalance,
    Candle,
    CandleInterval,
    ExchangeFeature,
    MarketMeta,
    MarketType,
    Position,
    PositionSide,
)

from .base import ExchangeClient


class BitgetAPIError(RuntimeError):
    """Raised when Bitget API responds with an error."""


@dataclass(slots=True)
class BitgetConfig:
    api_key: str
    api_secret: str
    passphrase: str
    base_url: str = "https://api.bitget.com"
    recv_window: int = 5000
    timeout: float = 10.0
    product_codes: dict[MarketType, str] = field(
        default_factory=lambda: {
            MarketType.SPOT: "spot",
            MarketType.LINEAR_SWAP: "USDT-FUTURES",
            MarketType.INVERSE_SWAP: "COIN-FUTURES",
        }
    )
    proxies: dict[str, str] | None = None


class BitgetClient(ExchangeClient):
    """Concrete ExchangeClient for Bitget REST endpoints."""

    name = "bitget"
    features = (
        ExchangeFeature.ACCOUNTS
        | ExchangeFeature.POSITIONS
        | ExchangeFeature.HISTORICAL_KLINES
        | ExchangeFeature.SPOT
        | ExchangeFeature.DERIVATIVES
    )

    def __init__(self, config: BitgetConfig, *, client: httpx.Client | None = None) -> None:
        self.config = config
        if client is not None:
            self._client = client
            return

        mounts: dict[str, httpx.HTTPTransport] | None = None
        if config.proxies:
            mounts = {
                scheme: httpx.HTTPTransport(proxy=proxy)
                for scheme, proxy in config.proxies.items()
            }
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout,
            mounts=mounts,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.close()

    # ------------------------------------------------------------------ helpers
    def supports(self, feature: ExchangeFeature) -> bool:
        return bool(self.features & feature)

    def _product_code(self, market_type: MarketType) -> str:
        try:
            return self.config.product_codes[market_type]
        except KeyError as exc:  # pragma: no cover
            raise ValueError(f"Unsupported market type: {market_type}") from exc

    def _format_symbol(self, symbol: str, market_type: MarketType) -> str:
        return symbol.replace("-", "").upper()

    def _normalize_symbol(self, symbol: str) -> str:
        return symbol.split("_")[0].upper()

    def _headers(self, method: str, request_path: str, body: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method.upper()}{request_path}{body}"
        mac = hmac.new(self.config.api_secret.encode(), message.encode(), hashlib.sha256)
        sign = base64.b64encode(mac.digest()).decode()
        return {
            "ACCESS-KEY": self.config.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.config.passphrase,
            "ACCESS-RECV-WINDOW": str(self.config.recv_window),
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        method = method.upper()
        qp = httpx.QueryParams(params or {})
        query = str(qp)
        request_path = path if not query else f"{path}?{query}"
        body_json = json.dumps(body) if body else ""
        headers = self._headers(method, request_path, body_json) if auth else None
        response = self._client.request(method, path, params=qp if params else None, json=body, headers=headers)
        try:
            payload = response.json()
        except ValueError as exc:  # pragma: no cover - unexpected
            response.raise_for_status()
            raise BitgetAPIError("Invalid JSON response from Bitget") from exc

        if response.status_code >= 400:
            code = payload.get("code", response.status_code)
            msg = payload.get("msg") or response.text
            raise BitgetAPIError(f"{code}: {msg}")

        code = payload.get("code")
        if code not in {"00000", "0"}:
            msg = payload.get("msg", "bitget request failed")
            raise BitgetAPIError(f"{code}: {msg}")
        return payload.get("data", [])

    # ------------------------------------------------------------------ metadata
    def list_markets(self, market_type: MarketType | None = None) -> Sequence[MarketMeta]:
        if market_type is None:
            markets: list[MarketMeta] = []
            for mt in (MarketType.SPOT, MarketType.LINEAR_SWAP, MarketType.INVERSE_SWAP):
                try:
                    markets.extend(self.list_markets(mt))
                except ValueError:
                    continue
            return markets

        if market_type == MarketType.SPOT:
            data = self._request("GET", "/api/v2/spot/public/symbols", auth=False)
            return [
                MarketMeta(
                    symbol=item["symbol"].upper(),
                    display_name=item.get("symbolName", item["symbol"]).upper(),
                    market_type=market_type,
                    base_asset=item["baseCoin"].upper(),
                    quote_asset=item["quoteCoin"].upper(),
                    price_precision=int(item.get("pricePrecision", item.get("priceScale", 4))),
                    size_precision=int(item.get("quantityPrecision", item.get("quantityScale", 4))),
                )
                for item in data
            ]

        product_type = self._product_code(market_type)
        data = self._request(
            "GET",
            "/api/v2/mix/market/contracts",
            params={"productType": product_type},
            auth=False,
        )
        return [
            MarketMeta(
                symbol=self._normalize_symbol(item["symbol"]),
                display_name=item["symbol"].upper(),
                market_type=market_type,
                base_asset=item.get("baseCoin", "").upper(),
                quote_asset=item.get("quoteCoin", "").upper(),
                price_precision=int(item.get("pricePlace", item.get("pricePrecision", 4))),
                size_precision=int(item.get("volumePlace", item.get("quantityPrecision", 4))),
                contract_value=Decimal(item.get("sizeMultiplier", item.get("contractSize", "0"))),
            )
            for item in data
        ]

    # ------------------------------------------------------------------ accounts
    def get_account_balances(
        self,
        market_type: MarketType,
        assets: Iterable[str] | None = None,
    ) -> Sequence[AccountBalance]:
        asset_filter = {asset.upper() for asset in assets} if assets else None
        if market_type == MarketType.SPOT:
            params = {"assetType": "all"}
            if asset_filter and len(asset_filter) == 1:
                params["coin"] = next(iter(asset_filter))
            data = self._request("GET", "/api/v2/spot/account/assets", params=params)
            entries = data if isinstance(data, list) else []
            return [
                self._to_account_balance(entry, market_type)
                for entry in entries
                if not asset_filter or entry["coin"].upper() in asset_filter
            ]

        product_type = self._product_code(market_type)
        data = self._request(
            "GET",
            "/api/v2/mix/account/accounts",
            params={"productType": product_type},
        )
        entries = data if isinstance(data, list) else []
        balances: list[AccountBalance] = []
        for entry in entries:
            asset_entries = entry.get("assetList")
            if isinstance(asset_entries, list) and asset_entries:
                for asset_entry in asset_entries:
                    asset = asset_entry.get("coin") or entry.get("marginCoin") or "USDT"
                    if asset_filter and asset.upper() not in asset_filter:
                        continue
                    merged_entry = {
                        **entry,
                        "coin": asset,
                        "available": asset_entry.get("available", entry.get("available", "0")),
                        "equity": asset_entry.get("balance", entry.get("accountEquity", "0")),
                    }
                    balances.append(
                        self._to_account_balance(merged_entry, market_type, asset_key="coin")
                    )
                continue

            asset = entry.get("marginCoin") or entry.get("coin") or "USDT"
            if asset_filter and asset.upper() not in asset_filter:
                continue
            balances.append(self._to_account_balance(entry, market_type, asset_key="marginCoin"))
        return balances

    def _to_account_balance(
        self,
        entry: dict[str, Any],
        market_type: MarketType,
        *,
        asset_key: str = "coin",
    ) -> AccountBalance:
        asset = entry.get(asset_key) or entry.get("coin") or entry.get("marginCoin", "USDT")
        if market_type == MarketType.SPOT:
            available_raw = entry.get("available", "0")
            frozen_raw = entry.get("frozen", "0")
            locked_raw = entry.get("locked", "0")
            total_raw = entry.get("total")
            if total_raw is None:
                total = Decimal(available_raw) + Decimal(frozen_raw) + Decimal(locked_raw)
            else:
                total = Decimal(total_raw)
            available = Decimal(available_raw)
        else:
            total = Decimal(
                entry.get("equity", entry.get("accountEquity", entry.get("available", "0")))
            )
            available = Decimal(
                entry.get("available", entry.get("maxTransferOut", entry.get("equity", "0")))
            )
        timestamp = self._entry_time(entry)
        return AccountBalance(
            asset=asset.upper(),
            total=total,
            available=available,
            market_type=market_type,
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------ positions
    def get_positions(
        self,
        market_type: MarketType,
        symbols: Iterable[str] | None = None,
    ) -> Sequence[Position]:
        if market_type == MarketType.SPOT:
            return []
        product_type = self._product_code(market_type)
        data = self._request(
            "GET",
            "/api/v2/mix/position/all-position",
            params={"productType": product_type},
        )
        symbol_filter = {sym.upper() for sym in symbols} if symbols else None
        positions: list[Position] = []
        for entry in data:
            symbol = self._normalize_symbol(entry["symbol"])
            if symbol_filter and symbol not in symbol_filter:
                continue
            positions.append(self._to_position(entry, market_type, symbol))
        return positions

    def _to_position(self, entry: dict[str, Any], market_type: MarketType, symbol: str) -> Position:
        side_raw = entry.get("holdSide", entry.get("positionSide", "net")).lower()
        if side_raw == "long":
            side = PositionSide.LONG
        elif side_raw == "short":
            side = PositionSide.SHORT
        else:
            side = PositionSide.NET
        timestamp = self._entry_time(entry)
        return Position(
            symbol=symbol,
            market_type=market_type,
            side=side,
            size=Decimal(entry.get("total", entry.get("holdVolume", "0"))),
            entry_price=Decimal(
                entry.get("openPriceAvg", entry.get("avgOpenPrice", entry.get("openPrice", "0")))
            ),
            mark_price=Decimal(entry.get("markPrice", "0")),
            leverage=Decimal(entry["leverage"]) if entry.get("leverage") else None,
            unrealized_pnl=Decimal(entry.get("unrealizedPL", entry.get("unrealizedPnl", "0"))),
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------ market data
    def fetch_klines(
        self,
        symbol: str,
        interval: CandleInterval,
        start_time: datetime,
        end_time: datetime | None = None,
        limit: int | None = None,
        market_type: MarketType | None = None,
    ) -> Sequence[Candle]:
        return self.fetch_history_candles(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            market_type=market_type,
        )

    def fetch_recent_candles(
        self,
        symbol: str,
        interval: CandleInterval,
        *,
        market_type: MarketType | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> Sequence[Candle]:
        market_type = market_type or MarketType.SPOT
        params = self._candle_params(
            symbol=symbol,
            interval=interval,
            market_type=market_type,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        path = (
            "/api/v2/spot/market/candles"
            if market_type == MarketType.SPOT
            else "/api/v2/mix/market/candles"
        )
        data = self._request("GET", path, params=params, auth=False)
        return self._parse_candles(data, symbol, interval, market_type, limit)

    def fetch_history_candles(
        self,
        symbol: str,
        interval: CandleInterval,
        start_time: datetime,
        end_time: datetime | None = None,
        limit: int | None = None,
        market_type: MarketType | None = None,
    ) -> Sequence[Candle]:
        market_type = market_type or MarketType.SPOT
        params = self._candle_params(
            symbol=symbol,
            interval=interval,
            market_type=market_type,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            history=True,
        )
        path = (
            "/api/v2/spot/market/history-candles"
            if market_type == MarketType.SPOT
            else "/api/v2/mix/market/history-candles"
        )
        data = self._request("GET", path, params=params, auth=False)
        return self._parse_candles(data, symbol, interval, market_type, limit)

    def _candle_params(
        self,
        *,
        symbol: str,
        interval: CandleInterval,
        market_type: MarketType,
        start_time: datetime | None,
        end_time: datetime | None,
        limit: int | None,
        history: bool = False,
    ) -> dict[str, str]:
        params = {
            "symbol": self._format_symbol(symbol, market_type),
            "granularity": self._interval_to_granularity(interval, market_type),
        }
        if market_type != MarketType.SPOT:
            params["productType"] = self._product_code(market_type)
        if start_time:
            params["startTime"] = str(int(start_time.replace(tzinfo=timezone.utc).timestamp() * 1000))
        if end_time:
            params["endTime"] = str(int(end_time.replace(tzinfo=timezone.utc).timestamp() * 1000))
        elif history:
            params["endTime"] = str(int(datetime.now(tz=timezone.utc).timestamp() * 1000))
        if limit:
            params["limit"] = str(limit)
        return params

    def _parse_candles(
        self,
        data: Sequence[Sequence[str]],
        symbol: str,
        interval: CandleInterval,
        market_type: MarketType,
        limit: int | None,
    ) -> Sequence[Candle]:
        granularity = self._interval_to_seconds(interval)
        candles: list[Candle] = []
        for row in reversed(data):  # Bitget returns newest first
            open_ts = int(row[0])
            open_time = datetime.fromtimestamp(open_ts / 1000, tz=timezone.utc)
            close_time = open_time + timedelta(seconds=granularity)
            turnover = None
            if market_type == MarketType.SPOT:
                turnover = Decimal(row[6]) if len(row) > 6 else None
            elif len(row) > 6:
                turnover = Decimal(row[6])
            candles.append(
                Candle(
                    symbol=symbol.upper(),
                    market_type=market_type,
                    interval=interval,
                    open_time=open_time,
                    close_time=close_time,
                    open=Decimal(row[1]),
                    high=Decimal(row[2]),
                    low=Decimal(row[3]),
                    close=Decimal(row[4]),
                    volume=Decimal(row[5]),
                    turnover=turnover,
                )
            )
        if limit:
            return candles[-limit:]
        return candles

    async def stream_klines(  # pragma: no cover - future work
        self,
        symbols: Sequence[str],
        interval: CandleInterval,
        market_type: MarketType | None = None,
    ):
        raise NotImplementedError("Realtime Bitget candles are not implemented yet.")

    # ------------------------------------------------------------------ utilities
    def _interval_to_seconds(self, interval: CandleInterval) -> int:
        mapping = {
            CandleInterval.MINUTE_1: 60,
            CandleInterval.MINUTE_5: 300,
            CandleInterval.MINUTE_15: 900,
            CandleInterval.HOUR_1: 3600,
            CandleInterval.HOUR_4: 14400,
            CandleInterval.DAY_1: 86400,
        }
        if interval not in mapping:  # pragma: no cover
            raise ValueError(f"Unsupported interval: {interval}")
        return mapping[interval]

    def _interval_to_granularity(self, interval: CandleInterval, market_type: MarketType) -> str:
        if market_type == MarketType.SPOT:
            mapping = {
                CandleInterval.MINUTE_1: "1min",
                CandleInterval.MINUTE_5: "5min",
                CandleInterval.MINUTE_15: "15min",
                CandleInterval.HOUR_1: "1h",
                CandleInterval.HOUR_4: "4h",
                CandleInterval.DAY_1: "1day",
            }
        else:
            mapping = {
                CandleInterval.MINUTE_1: "1m",
                CandleInterval.MINUTE_5: "5m",
                CandleInterval.MINUTE_15: "15m",
                CandleInterval.HOUR_1: "1H",
                CandleInterval.HOUR_4: "4H",
                CandleInterval.DAY_1: "1D",
            }
        if interval not in mapping:  # pragma: no cover
            raise ValueError(f"Unsupported interval: {interval}")
        return mapping[interval]

    def _entry_time(self, entry: dict[str, Any]) -> datetime:
        for key in ("uTime", "updateTime", "ts", "cTime", "systemTime"):
            if key in entry and entry[key]:
                return datetime.fromtimestamp(int(entry[key]) / 1000, tz=timezone.utc)
        return datetime.now(tz=timezone.utc)


__all__ = ["BitgetClient", "BitgetConfig", "BitgetAPIError"]
