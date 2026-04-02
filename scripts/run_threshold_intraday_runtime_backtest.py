"""Run Runtime Core backtest for ThresholdIntradayStrategy on BTCUSDT 5m data."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from xtrader.backtests import EventDrivenBacktestConfig
from xtrader.runtime import RuntimeCore
from xtrader.strategies import ThresholdIntradayStrategy

_TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="configs/runtime/threshold_intraday_btcusdt_5m_3y.strategy.json",
        help="Runtime config path",
    )
    parser.add_argument("--exchange", default="bitget")
    parser.add_argument("--market-type", default="linear_swap")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--start", default="2023-04-01T00:00:00Z")
    parser.add_argument("--end", default="2026-04-01T00:00:00Z")
    parser.add_argument("--signal-column", default="macd_12_26_9_hist")
    parser.add_argument("--entry-threshold", type=float, default=35.0)
    parser.add_argument("--exit-threshold", type=float, default=5.0)
    parser.add_argument("--position-size", type=float, default=0.02)
    parser.add_argument("--stop-loss", type=float, default=0.01)
    parser.add_argument("--take-profit", type=float, default=0.02)
    parser.add_argument("--time-stop-bars", type=int, default=24)
    parser.add_argument("--daily-loss-limit", type=float, default=0.03)
    parser.add_argument("--taker-fee-bps", type=float, default=6.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--initial-equity", type=float, default=1000.0)
    parser.add_argument(
        "--code-version",
        default="git:0123456789abcdef0123456789abcdef01234567",
        help="Use explicit code_version because current workspace may not be a git repo",
    )
    parser.add_argument(
        "--run-root",
        default="",
        help="Optional explicit run root; defaults to runs/runtime/threshold_intraday/<timestamp>_btcusdt_5m_3y",
    )
    return parser.parse_args()


def _load_bars(*, exchange: str, market_type: str, symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    root = Path("data/klines") / exchange / market_type / symbol / interval
    parts = sorted(root.glob("*/*.parquet"))
    if not parts:
        raise FileNotFoundError(f"no parquet files found under {root}")

    frames: list[pd.DataFrame] = []
    for path in parts:
        frame = pd.read_parquet(path)
        if "open_time_ms" in frame.columns:
            frame["timestamp"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True, errors="coerce")
        elif "timestamp" in frame.columns:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        else:
            raise ValueError(f"{path} missing open_time_ms/timestamp column")

        frame = frame[(frame["timestamp"] >= start) & (frame["timestamp"] < end)]
        if frame.empty:
            continue
        frames.append(frame)

    if not frames:
        raise ValueError(f"no bars in range [{start}, {end}) for {exchange}.{market_type}.{symbol}.{interval}")

    bars = pd.concat(frames, ignore_index=True)
    bars["symbol"] = bars.get("symbol", symbol).astype(str).str.upper()
    for column in ("open", "high", "low", "close", "volume"):
        if column not in bars.columns:
            raise ValueError(f"bars missing required column: {column}")
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    if "funding_rate" in bars.columns:
        bars["funding_rate"] = pd.to_numeric(bars["funding_rate"], errors="coerce").fillna(0.0)
    else:
        bars["funding_rate"] = 0.0

    bars = (
        bars.dropna(subset=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )
    return bars[["timestamp", "symbol", "open", "high", "low", "close", "volume", "funding_rate"]]


def _default_run_root() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("runs") / "runtime" / "threshold_intraday" / f"{ts}_btcusdt_5m_3y"


def _load_config(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("runtime config root must be object")
    return payload


def main() -> int:
    args = _parse_args()
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    if start >= end:
        raise ValueError("start must be before end")

    config = _load_config(args.config)
    bars = _load_bars(
        exchange=args.exchange,
        market_type=args.market_type,
        symbol=args.symbol.upper(),
        interval=args.interval,
        start=start,
        end=end,
    )
    if args.interval not in _TIMEFRAME_MS:
        raise ValueError(f"unsupported interval for backtest_config: {args.interval}")

    run_root = Path(args.run_root) if args.run_root else _default_run_root()
    strategy = ThresholdIntradayStrategy(signal_column=args.signal_column)
    runtime = RuntimeCore()
    result = runtime.run(
        config=config,
        data_source={
            "strategy": strategy,
            "bars_by_timeframe": {args.interval: bars},
            "strategy_params": {
                "entry_threshold": float(args.entry_threshold),
                "exit_threshold": float(args.exit_threshold),
                "position_size": float(args.position_size),
                "stop_loss": float(args.stop_loss),
                "take_profit": float(args.take_profit),
                "time_stop_bars": int(args.time_stop_bars),
                "daily_loss_limit": float(args.daily_loss_limit),
            },
            "run_root": run_root,
            "code_version": str(args.code_version),
            "backtest_config": EventDrivenBacktestConfig(
                symbol=args.symbol.upper(),
                interval_ms=int(_TIMEFRAME_MS[args.interval]),
                execution_lag_bars=1,
                taker_fee_bps=float(args.taker_fee_bps),
                slippage_bps=float(args.slippage_bps),
                initial_equity=float(args.initial_equity),
            ),
        },
        mode="backtest",
    )

    print(f"runtime_status={result.status}")
    print(f"run_root={run_root}")
    if result.error_code:
        print(f"error_code={result.error_code}")
    if result.error_message:
        print(f"error_message={result.error_message}")

    summary_path = run_root / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for key in ("trade_count", "skipped_signal_count", "net_return", "max_drawdown", "win_rate"):
            if key in summary:
                print(f"{key}={summary[key]}")
    manifest_path = run_root / "run_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        perf = manifest.get("performance_log", {})
        if isinstance(perf, dict):
            for key in ("elapsed_ms", "peak_rss_mb", "bars_count", "trials_count"):
                if key in perf:
                    print(f"{key}={perf[key]}")

    return 0 if result.status in {"SUCCESS", "PARTIAL_SUCCESS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
