from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import pytest

from xtrader.common.models import CandleInterval, ExchangeFeature, MarketType, PositionSide
from xtrader.exchanges.bitget import BitgetAPIError, BitgetClient, BitgetConfig


def make_client(responses: dict[tuple[str, str], dict[str, Any]] | None = None) -> BitgetClient:
    response_map = responses or {}

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        payload = response_map.get(key)
        if payload is None:  # pragma: no cover - ensures test fails loudly
            return httpx.Response(404, json={"code": "404", "msg": "not mocked"})
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    config = BitgetConfig(api_key="k", api_secret="s", passphrase="p")
    http_client = httpx.Client(base_url="https://api.bitget.com", transport=transport)
    return BitgetClient(config, client=http_client)


def test_get_account_balances_spot():
    client = make_client(
        {
            ("GET", "/api/v2/spot/account/assets"): {
                "code": "00000",
                "data": [
                    {
                        "coin": "USDT",
                        "available": "12.5",
                        "frozen": "2",
                        "locked": "0.5",
                        "uTime": "1711410000000",
                    },
                    {"coin": "BTC", "available": "0.1", "frozen": "0", "locked": "0", "uTime": "1711410000000"},
                ],
            }
        }
    )

    balances = client.get_account_balances(MarketType.SPOT, assets=["USDT"])

    assert len(balances) == 1
    usdt = balances[0]
    assert usdt.asset == "USDT"
    assert usdt.total == Decimal("15.0")
    assert usdt.available == Decimal("12.5")
    assert usdt.market_type is MarketType.SPOT
    assert usdt.timestamp == datetime.fromtimestamp(1711410000000 / 1000, tz=timezone.utc)


def test_get_account_balances_linear_uses_v2_asset_list():
    client = make_client(
        {
            ("GET", "/api/v2/mix/account/accounts"): {
                "code": "00000",
                "data": [
                    {
                        "marginCoin": "USDT",
                        "accountEquity": "150.5",
                        "available": "80",
                        "uTime": "1711410000000",
                        "assetList": [
                            {"coin": "USDT", "balance": "150.5", "available": "80"},
                            {"coin": "BTC", "balance": "0.02", "available": "0.01"},
                        ],
                    }
                ],
            }
        }
    )

    balances = client.get_account_balances(MarketType.LINEAR_SWAP, assets=["BTC"])

    assert len(balances) == 1
    btc = balances[0]
    assert btc.asset == "BTC"
    assert btc.total == Decimal("0.02")
    assert btc.available == Decimal("0.01")
    assert btc.market_type is MarketType.LINEAR_SWAP


def test_get_positions_linear():
    client = make_client(
        {
            ("GET", "/api/v2/mix/position/all-position"): {
                "code": "00000",
                "data": [
                    {
                        "symbol": "BTCUSDT",
                        "holdSide": "long",
                        "total": "0.01",
                        "openPriceAvg": "50000",
                        "markPrice": "50500",
                        "leverage": "20",
                        "unrealizedPL": "10",
                        "uTime": "1711410000000",
                    }
                ],
            }
        }
    )

    positions = client.get_positions(MarketType.LINEAR_SWAP)

    assert len(positions) == 1
    pos = positions[0]
    assert pos.symbol == "BTCUSDT"
    assert pos.side is PositionSide.LONG
    assert pos.size == Decimal("0.01")
    assert pos.entry_price == Decimal("50000")
    assert pos.mark_price == Decimal("50500")
    assert pos.unrealized_pnl == Decimal("10")
    assert pos.market_type is MarketType.LINEAR_SWAP


def test_fetch_klines_spot_uses_history_endpoint():
    client = make_client(
        {
            ("GET", "/api/v2/spot/market/history-candles"): {
                "code": "00000",
                "data": [
                    ["1711410060000", "60200", "61000", "60100", "60800", "10", "608000", "608000"],
                    ["1711410000000", "60000", "60500", "59500", "60200", "12", "720000", "720000"],
                ],
            }
        }
    )

    candles = client.fetch_klines(
        symbol="BTCUSDT",
        interval=CandleInterval.MINUTE_1,
        start_time=datetime(2024, 3, 26, tzinfo=timezone.utc),
        market_type=MarketType.SPOT,
    )

    assert len(candles) == 2
    first = candles[0]
    assert first.open == Decimal("60000")
    assert first.volume == Decimal("12")
    assert first.turnover == Decimal("720000")
    assert first.market_type is MarketType.SPOT
    assert first.close_time > first.open_time


def test_fetch_recent_candles_linear_uses_v2_mix_endpoint():
    client = make_client(
        {
            ("GET", "/api/v2/mix/market/candles"): {
                "code": "00000",
                "data": [
                    ["1711410060000", "60200", "61000", "60100", "60800", "10", "608000"],
                    ["1711410000000", "60000", "60500", "59500", "60200", "12", "720000"],
                ],
            }
        }
    )

    candles = client.fetch_recent_candles(
        symbol="BTCUSDT",
        interval=CandleInterval.MINUTE_1,
        market_type=MarketType.LINEAR_SWAP,
        limit=2,
    )

    assert len(candles) == 2
    first = candles[0]
    assert first.open == Decimal("60000")
    assert first.volume == Decimal("12")
    assert first.turnover == Decimal("720000")
    assert first.market_type is MarketType.LINEAR_SWAP


def test_fetch_recent_candles_linear_uses_v2_product_type():
    seen_product_type: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_product_type
        seen_product_type = request.url.params.get("productType")
        return httpx.Response(
            200,
            json={
                "code": "00000",
                "data": [["1711410000000", "60000", "60500", "59500", "60200", "12", "720000"]],
            },
        )

    transport = httpx.MockTransport(handler)
    config = BitgetConfig(api_key="k", api_secret="s", passphrase="p")
    http_client = httpx.Client(base_url="https://api.bitget.com", transport=transport)
    client = BitgetClient(config, client=http_client)

    client.fetch_recent_candles(
        symbol="BTCUSDT",
        interval=CandleInterval.MINUTE_1,
        market_type=MarketType.LINEAR_SWAP,
    )

    assert seen_product_type == "USDT-FUTURES"


def test_get_positions_linear_uses_v2_product_type():
    seen_product_type: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_product_type
        seen_product_type = request.url.params.get("productType")
        return httpx.Response(
            200,
            json={
                "code": "00000",
                "data": [
                    {
                        "symbol": "BTCUSDT",
                        "holdSide": "long",
                        "total": "0.01",
                        "openPriceAvg": "50000",
                        "markPrice": "50500",
                        "leverage": "20",
                        "unrealizedPL": "10",
                        "uTime": "1711410000000",
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    config = BitgetConfig(api_key="k", api_secret="s", passphrase="p")
    http_client = httpx.Client(base_url="https://api.bitget.com", transport=transport)
    client = BitgetClient(config, client=http_client)

    client.get_positions(MarketType.LINEAR_SWAP)

    assert seen_product_type == "USDT-FUTURES"


def test_list_markets_combined():
    client = make_client(
        {
            ("GET", "/api/v2/spot/public/symbols"): {
                "code": "00000",
                "data": [
                    {
                        "symbol": "BTCUSDT",
                        "baseCoin": "BTC",
                        "quoteCoin": "USDT",
                        "pricePrecision": "4",
                        "quantityPrecision": "3",
                    }
                ],
            },
            ("GET", "/api/v2/mix/market/contracts"): {
                "code": "00000",
                "data": [
                    {
                        "symbol": "BTCUSDT",
                        "baseCoin": "BTC",
                        "quoteCoin": "USDT",
                        "pricePlace": "2",
                        "volumePlace": "3",
                        "sizeMultiplier": "0.001",
                    }
                ],
            },
        }
    )

    markets = client.list_markets()

    assert len(markets) >= 2
    spot = next(m for m in markets if m.market_type is MarketType.SPOT)
    swap = next(m for m in markets if m.market_type is MarketType.LINEAR_SWAP)
    assert spot.symbol == "BTCUSDT"
    assert swap.symbol == "BTCUSDT"
    assert swap.contract_value == Decimal("0.001")


def test_supports_flags():
    client = make_client()
    assert client.supports(ExchangeFeature.ACCOUNTS)
    assert not client.supports(ExchangeFeature.REALTIME_KLINES)


def test_http_error_raised_as_bitget_api_error():
    client = make_client(
        {
            ("GET", "/api/v2/spot/account/assets"): {
                "code": "40017",
                "msg": "invalid timestamp",
                "data": None,
            }
        }
    )

    with pytest.raises(BitgetAPIError):
        client.get_account_balances(MarketType.SPOT)
