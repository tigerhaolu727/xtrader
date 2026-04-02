"""Run ThresholdIntradayStrategy with 15m execution from local 5m candles."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from xtrader.backtests import (
    EventDrivenBacktestConfig,
    EventDrivenBacktestResult,
    run_event_driven_backtest,
    write_strategy_event_driven_outputs,
)
from xtrader.data.storage import KlineLocalStore
from xtrader.strategies import StrategyContext, ThresholdIntradayStrategy


def parse_datetime(value: str) -> datetime:
    text = str(value).strip()
    if text.isdigit():
        raw = int(text)
        if len(text) >= 13:
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    normalized = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_utc_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.astimezone(timezone.utc).timestamp() * 1000)


def _interval_rule(timeframe: str) -> str:
    mapping = {
        "5m": "5min",
        "15m": "15min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }
    key = str(timeframe).strip().lower()
    if key not in mapping:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return mapping[key]


def _normalize_timeframes(value: str) -> list[str]:
    items = [item.strip().lower() for item in str(value).split(",")]
    out: list[str] = []
    for item in items:
        if not item:
            continue
        if item not in out:
            out.append(item)
    return out


def load_5m_prices(
    *,
    data_root: Path,
    exchange: str,
    market_type: str,
    symbol: str,
    start_time: datetime,
    end_time: datetime,
) -> pd.DataFrame:
    store = KlineLocalStore(
        root_dir=data_root / "klines",
        index_dir=data_root / "klines_index",
    )
    raw = store.load_records(
        exchange=exchange,
        market_type=market_type,
        symbol=symbol.upper(),
        interval="5m",
        start_ms=_to_utc_ms(start_time),
        end_ms=_to_utc_ms(end_time),
    )
    if raw.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", "open", "high", "low", "close", "volume", "funding_rate"])
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(raw["open_time_ms"], unit="ms", utc=True, errors="coerce"),
            "symbol": raw["symbol"].astype(str).str.upper(),
            "open": pd.to_numeric(raw["open"], errors="coerce"),
            "high": pd.to_numeric(raw["high"], errors="coerce"),
            "low": pd.to_numeric(raw["low"], errors="coerce"),
            "close": pd.to_numeric(raw["close"], errors="coerce"),
            "volume": pd.to_numeric(raw["volume"], errors="coerce"),
        }
    )
    frame["funding_rate"] = 0.0
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)
    return frame


def resample_ohlc(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if timeframe == "5m":
        return frame.copy().reset_index(drop=True)
    rule = _interval_rule(timeframe)
    symbol = str(frame["symbol"].iloc[0]) if "symbol" in frame.columns and not frame.empty else "BTCUSDT"
    source = frame.copy().set_index("timestamp")
    grouped = (
        source[["open", "high", "low", "close", "volume"]]
        .resample(rule, label="right", closed="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    grouped["symbol"] = symbol
    grouped["funding_rate"] = 0.0
    return grouped[["timestamp", "symbol", "open", "high", "low", "close", "volume", "funding_rate"]].reset_index(drop=True)


def build_signal_features(price_15m: pd.DataFrame, signal_window: int) -> pd.DataFrame:
    if price_15m.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", "value"])
    frame = price_15m.copy()
    ret = frame["close"].pct_change().fillna(0.0)
    vol = ret.rolling(window=max(2, signal_window), min_periods=max(2, signal_window // 4)).std()
    signal = (ret / vol).replace([float("inf"), float("-inf")], 0.0).fillna(0.0).clip(-5.0, 5.0)
    return pd.DataFrame(
        {
            "timestamp": frame["timestamp"],
            "symbol": frame["symbol"].astype(str).str.upper(),
            "value": signal.astype(float),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ThresholdIntraday 15m execution backtest from local 5m candles.")
    parser.add_argument("--exchange", default="bitget")
    parser.add_argument("--market-type", default="linear_swap")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start-time", help="ISO8601 or unix timestamp (s/ms). Default: now-3y (UTC)")
    parser.add_argument("--end-time", help="ISO8601 or unix timestamp (s/ms). Default: now (UTC)")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--report-base", default="reports/backtests/strategy")
    parser.add_argument("--run-suffix", default="btcusdt_15m_exec_from_5m")
    parser.add_argument("--resampled-timeframes", default="15m,1h,4h,1d")
    parser.add_argument("--base-snapshot-timeframe", choices=["5m", "15m"], default="5m")

    parser.add_argument("--entry-threshold", type=float, default=0.5)
    parser.add_argument("--exit-threshold", type=float, default=0.1)
    parser.add_argument("--position-size", type=float, default=1.0)
    parser.add_argument("--stop-loss", type=float, default=0.01)
    parser.add_argument("--take-profit", type=float, default=0.02)
    parser.add_argument("--time-stop-bars", type=int, default=24)
    parser.add_argument("--daily-loss-limit", type=float, default=0.03)
    parser.add_argument("--signal-window", type=int, default=48)

    parser.add_argument("--execution-lag-bars", type=int, default=1)
    parser.add_argument("--taker-fee-bps", type=float, default=6.0)
    parser.add_argument("--maker-fee-bps", type=float, default=2.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--initial-equity", type=float, default=1.0)
    return parser


def run(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    now_utc = datetime.now(tz=timezone.utc)
    end_time = parse_datetime(args.end_time) if args.end_time else now_utc
    start_time = parse_datetime(args.start_time) if args.start_time else (end_time - timedelta(days=365 * 3))
    if end_time <= start_time:
        raise ValueError("end_time must be greater than start_time")

    symbol = str(args.symbol).upper()
    data_root = Path(args.data_root)
    report_base = Path(args.report_base)

    price_5m = load_5m_prices(
        data_root=data_root,
        exchange=str(args.exchange),
        market_type=str(args.market_type),
        symbol=symbol,
        start_time=start_time,
        end_time=end_time,
    )
    if price_5m.empty:
        raise RuntimeError("No local 5m candles found in requested range. Please verify data/klines coverage.")

    price_15m = resample_ohlc(price_5m, "15m")
    features = build_signal_features(price_15m, signal_window=int(args.signal_window))
    if features.empty or price_15m.empty:
        raise RuntimeError("Resampled 15m frame is empty; cannot run 15m execution backtest.")

    strategy = ThresholdIntradayStrategy()
    context = StrategyContext(
        as_of_time=pd.Timestamp(features["timestamp"].iloc[-1]).to_pydatetime(),
        universe=(symbol,),
        inputs={"features": features},
        params={
            "entry_threshold": float(args.entry_threshold),
            "exit_threshold": float(args.exit_threshold),
            "position_size": float(args.position_size),
            "stop_loss": float(args.stop_loss),
            "take_profit": float(args.take_profit),
            "time_stop_bars": int(args.time_stop_bars),
            "daily_loss_limit": float(args.daily_loss_limit),
        },
    )
    actions = strategy.generate_actions(context).actions

    config = EventDrivenBacktestConfig(
        symbol=symbol,
        interval_ms=900_000,
        execution_lag_bars=int(args.execution_lag_bars),
        taker_fee_bps=float(args.taker_fee_bps),
        maker_fee_bps=float(args.maker_fee_bps),
        slippage_bps=float(args.slippage_bps),
        initial_equity=float(args.initial_equity),
        default_stop_loss=float(args.stop_loss),
        default_take_profit=float(args.take_profit),
        default_time_stop_bars=int(args.time_stop_bars),
        default_daily_loss_limit=float(args.daily_loss_limit),
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=price_15m,
        config=config,
    )

    # Keep UI kline source configurable: 5m (default) or 15m (execution timeframe).
    base_snapshot = price_5m if args.base_snapshot_timeframe == "5m" else price_15m
    output_result = EventDrivenBacktestResult(
        trades=result.trades,
        equity_curve=result.equity_curve,
        summary=result.summary,
        diagnostics=result.diagnostics,
        price_input_snapshot=base_snapshot.copy(),
        action_input_snapshot=result.action_input_snapshot.copy(),
    )

    tf_list = _normalize_timeframes(args.resampled_timeframes)
    resampled_frames: dict[str, pd.DataFrame] = {}
    for timeframe in tf_list:
        if timeframe == "15m":
            resampled_frames[timeframe] = price_15m.copy()
        elif timeframe == "5m":
            resampled_frames[timeframe] = price_5m.copy()
        else:
            resampled_frames[timeframe] = resample_ohlc(price_5m, timeframe)

    outputs = write_strategy_event_driven_outputs(
        strategy_name="Threshold Intraday",
        config=config,
        result=output_result,
        report_base=report_base,
        run_suffix=str(args.run_suffix),
        resampled_price_frames=resampled_frames,
    )

    payload = {
        "run_manifest_path": outputs.get("run_manifest_path"),
        "report_root": outputs.get("report_root"),
        "symbol": symbol,
        "execution_timeframe": "15m",
        "base_snapshot_timeframe": args.base_snapshot_timeframe,
        "rows": {
            "price_5m": int(len(price_5m.index)),
            "price_15m": int(len(price_15m.index)),
            "features_15m": int(len(features.index)),
            "actions": int(len(actions.index)),
            "trades": int(len(result.trades.index)),
        },
        "summary": asdict(result.summary),
        "note": (
            "UI当前主K线读取 prices 数据集（来自 snapshots/base + chunks/prices）。"
            "resampled/* 主要用于多粒度补充，不会自动替代主K线源。"
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
