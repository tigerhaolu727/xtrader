"""Run ProfileActionStrategy smoke backtest on local BTCUSDT 5m candles."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from xtrader.backtests import (
    EventDrivenBacktestConfig,
    run_event_driven_backtest,
    write_strategy_event_driven_outputs,
)
from xtrader.strategies import ProfileActionStrategy, StrategyContext

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


def _parse_time(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _load_bars(
    *,
    data_root: Path,
    exchange: str,
    market_type: str,
    symbol: str,
    interval: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    root = data_root / "klines" / exchange / market_type / symbol / interval
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
        raise ValueError(
            f"no bars in range [{start.isoformat()}, {end.isoformat()}) "
            f"for {exchange}.{market_type}.{symbol}.{interval}"
        )

    bars = pd.concat(frames, ignore_index=True)
    bars["symbol"] = bars.get("symbol", symbol).astype(str).str.upper()
    required = ("open", "high", "low", "close", "volume")
    for column in required:
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        default="configs/strategy-profiles/five_min_regime_momentum/v0.3.json",
        help="StrategyProfile JSON path",
    )
    parser.add_argument("--exchange", default="bitget")
    parser.add_argument("--market-type", default="linear_swap")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--start", default="2026-01-01T00:00:00Z")
    parser.add_argument("--end", default="2026-03-01T00:00:00Z")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--report-base", default="reports/backtests/strategy")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-suffix", default="btcusdt_5m_profile_smoke_v03")
    parser.add_argument("--taker-fee-bps", type=float, default=6.0)
    parser.add_argument("--maker-fee-bps", type=float, default=2.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--initial-equity", type=float, default=10_000.0)
    parser.add_argument("--account-equity", type=float, default=10_000.0)
    parser.add_argument("--daily-pnl-pct", type=float, default=0.0)
    parser.add_argument("--open-positions", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    symbol = str(args.symbol).upper()
    interval = str(args.interval).lower()
    if interval not in _TIMEFRAME_MS:
        raise ValueError(f"unsupported interval for backtest_config: {interval}")
    start = _parse_time(str(args.start))
    end = _parse_time(str(args.end))
    if start >= end:
        raise ValueError("start must be before end")

    bars = _load_bars(
        data_root=Path(args.data_root),
        exchange=str(args.exchange),
        market_type=str(args.market_type),
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
    )
    if bars.empty:
        raise RuntimeError("loaded bars is empty")

    strategy = ProfileActionStrategy(profile_config=Path(args.profile))
    context = StrategyContext(
        as_of_time=pd.Timestamp(bars["timestamp"].iloc[-1]).to_pydatetime(),
        universe=(symbol,),
        inputs={interval: bars},
        meta={
            "account_context": {
                "equity": float(args.account_equity),
                "daily_pnl_pct": float(args.daily_pnl_pct),
                "open_positions": int(args.open_positions),
            }
        },
    )
    strategy_result = strategy.generate_actions(context)
    actions = strategy_result.actions.copy(deep=True)

    backtest_config = EventDrivenBacktestConfig(
        symbol=symbol,
        interval_ms=int(_TIMEFRAME_MS[interval]),
        execution_lag_bars=1,
        taker_fee_bps=float(args.taker_fee_bps),
        maker_fee_bps=float(args.maker_fee_bps),
        slippage_bps=float(args.slippage_bps),
        initial_equity=float(args.initial_equity),
    )
    backtest_result = run_event_driven_backtest(
        actions=actions,
        price_frame=bars,
        config=backtest_config,
    )

    outputs = write_strategy_event_driven_outputs(
        strategy_name="Profile Action",
        config=backtest_config,
        result=backtest_result,
        decision_trace=strategy_result.decision_trace,
        report_base=Path(args.report_base),
        run_id=str(args.run_id).strip() or None,
        run_suffix=str(args.run_suffix),
        price_frame=bars,
        actions=actions,
        signal_interval_ms=int(_TIMEFRAME_MS[interval]),
    )

    payload = {
        "status": "SUCCESS",
        "profile": str(args.profile),
        "symbol": symbol,
        "interval": interval,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": {
            "bars": int(len(bars.index)),
            "actions": int(len(actions.index)),
            "trades": int(len(backtest_result.trades.index)),
        },
        "summary": asdict(backtest_result.summary),
        "artifacts": {
            "report_root": outputs.get("report_root"),
            "summary_path": outputs.get("summary_path"),
            "diagnostics_path": outputs.get("diagnostics_path"),
            "trades_path": outputs.get("trades_parquet_path"),
            "equity_curve_path": outputs.get("equity_curve_parquet_path"),
            "signal_execution_path": outputs.get("signal_execution_path"),
            "decision_trace_path": outputs.get("decision_trace_path"),
            "run_manifest_path": outputs.get("run_manifest_path"),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
