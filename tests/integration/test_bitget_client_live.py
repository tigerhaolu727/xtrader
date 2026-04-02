from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

from xtrader.common.models import CandleInterval, MarketType
from xtrader.exchanges.bitget import BitgetAPIError, BitgetClient, BitgetConfig

REQUIRED_ENV = ("BITGET_API_KEY", "BITGET_API_SECRET", "BITGET_PASSPHRASE")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

def _has_credentials() -> bool:
    return all(os.getenv(var) for var in REQUIRED_ENV)


skip_reason = "Bitget API credentials not provided via environment variables."


def _build_config() -> BitgetConfig:
    proxies: dict[str, str] | None = None
    http_proxy = os.getenv("BITGET_HTTP_PROXY")
    https_proxy = os.getenv("BITGET_HTTPS_PROXY")
    if http_proxy or https_proxy:
        proxies = {}
        if http_proxy:
            proxies["http://"] = http_proxy
        if https_proxy:
            proxies["https://"] = https_proxy

    return BitgetConfig(
        api_key=os.getenv("BITGET_API_KEY", ""),
        api_secret=os.getenv("BITGET_API_SECRET", ""),
        passphrase=os.getenv("BITGET_PASSPHRASE", ""),
        proxies=proxies,
    )


def test_bitget_live_public_candles():
    start = datetime.now(tz=timezone.utc) - timedelta(minutes=30)
    config = _build_config()
    with BitgetClient(config) as client:
        history_candles = client.fetch_history_candles(
            symbol="BTCUSDT",
            interval=CandleInterval.MINUTE_1,
            start_time=start,
            market_type=MarketType.SPOT,
            limit=10,
        )
        assert history_candles, "Expected live historical candle data from Bitget"

        recent_candles = client.fetch_recent_candles(
            symbol="BTCUSDT",
            interval=CandleInterval.MINUTE_1,
            start_time=start,
            market_type=MarketType.SPOT,
            limit=10,
        )
        assert recent_candles, "Expected recent candle data from Bitget"


@pytest.mark.skipif(not _has_credentials(), reason=skip_reason)
def test_bitget_live_spot_balances():
    config = _build_config()
    with BitgetClient(config) as client:
        try:
            balances = client.get_account_balances(MarketType.SPOT)
        except BitgetAPIError as exc:
            if str(exc).startswith("40014:"):
                pytest.skip(f"Bitget API key lacks spot balance permission: {exc}")
            raise
        assert isinstance(balances, list)


@pytest.mark.skipif(not _has_credentials(), reason=skip_reason)
def test_bitget_live_linear_positions():
    config = _build_config()
    with BitgetClient(config) as client:
        try:
            positions = client.get_positions(MarketType.LINEAR_SWAP)
        except BitgetAPIError as exc:
            if str(exc).startswith("40014:"):
                pytest.skip(f"Bitget API key lacks futures position permission: {exc}")
            raise
        assert isinstance(positions, list)
