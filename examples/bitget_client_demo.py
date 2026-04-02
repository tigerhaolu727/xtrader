#!/usr/bin/env python3
"""Minimal Bitget client demo."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from xtrader.common.models import CandleInterval, MarketType
from xtrader.exchanges.bitget import BitgetClient, BitgetConfig


def load_config() -> BitgetConfig:
    missing = [var for var in ("BITGET_API_KEY", "BITGET_API_SECRET", "BITGET_PASSPHRASE") if var not in os.environ]
    if missing:
        raise SystemExit(f"Missing environment variables: {', '.join(missing)}")
    return BitgetConfig(
        api_key=os.environ["BITGET_API_KEY"],
        api_secret=os.environ["BITGET_API_SECRET"],
        passphrase=os.environ["BITGET_PASSPHRASE"],
    )


def main() -> None:
    config = load_config()
    start = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    with BitgetClient(config) as client:
        balances = client.get_account_balances(MarketType.SPOT)
        print(f"Spot balances count: {len(balances)}")

        candles = client.fetch_klines(
            symbol="BTCUSDT",
            interval=CandleInterval.MINUTE_5,
            start_time=start,
            market_type=MarketType.SPOT,
        )
        print(f"Fetched {len(candles)} candles. Latest close: {candles[-1].close if candles else 'n/a'}")


if __name__ == "__main__":
    main()
