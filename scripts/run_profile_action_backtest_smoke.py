"""Run ProfileActionStrategy smoke backtest with profile-driven multi-timeframe assembly."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

from xtrader.backtests import (
    EventDrivenBacktestConfig,
    build_strategy_report_root,
)
from xtrader.runtime import RuntimeCore
from xtrader.strategies import (
    ActionStrategyResult,
    BaseActionStrategy,
    ProfileActionStrategy,
    StrategyContext,
    StrategySpec,
)
from xtrader.strategy_profiles import StrategyProfilePrecompileEngine

_TIMEFRAME_PATTERN = re.compile(r"^(?P<num>[1-9][0-9]*)(?P<unit>[smhdw])$")
_TIMEFRAME_UNIT_MS: dict[str, int] = {
    "s": 1_000,
    "m": 60_000,
    "h": 3_600_000,
    "d": 86_400_000,
    "w": 604_800_000,
}
_TIMEFRAME_RULE_SUFFIX: dict[str, str] = {
    "s": "s",
    "m": "min",
    "h": "h",
    "d": "d",
    "w": "W",
}
_BAR_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "open", "high", "low", "close", "volume", "funding_rate")


def _parse_time(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _timeframe_to_ms(value: str) -> int:
    text = str(value).strip().lower()
    matched = _TIMEFRAME_PATTERN.fullmatch(text)
    if not matched:
        raise ValueError(f"unsupported timeframe: {value}")
    size = int(matched.group("num"))
    unit = str(matched.group("unit"))
    return size * _TIMEFRAME_UNIT_MS[unit]


def _timeframe_to_rule(value: str) -> str:
    text = str(value).strip().lower()
    matched = _TIMEFRAME_PATTERN.fullmatch(text)
    if not matched:
        raise ValueError(f"unsupported timeframe: {value}")
    size = int(matched.group("num"))
    unit = str(matched.group("unit"))
    return f"{size}{_TIMEFRAME_RULE_SUFFIX[unit]}"


def _sorted_timeframes(values: list[str]) -> list[str]:
    return sorted({str(item).strip().lower() for item in values}, key=_timeframe_to_ms)


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
        .drop_duplicates(subset=["timestamp", "symbol"], keep="last")
        .reset_index(drop=True)
    )
    return bars[list(_BAR_COLUMNS)]


def _scan_data_catalog(*, data_root: Path) -> dict[str, object]:
    klines_root = data_root / "klines"
    by_key: dict[tuple[str, str, str, str], dict[str, object]] = {}
    if not klines_root.exists():
        return {
            "schema_version": "xtr_data_catalog_v1",
            "generated_at": pd.Timestamp.utcnow().isoformat(),
            "root": str(klines_root),
            "entries": [],
        }

    for path in klines_root.rglob("*.parquet"):
        rel = path.relative_to(klines_root)
        if len(rel.parts) < 5:
            continue
        exchange, market_type, symbol, interval = (
            str(rel.parts[0]).lower(),
            str(rel.parts[1]).lower(),
            str(rel.parts[2]).upper(),
            str(rel.parts[3]).lower(),
        )
        partition = str(rel.parts[4])
        key = (exchange, market_type, symbol, interval)
        payload = by_key.get(key)
        if payload is None:
            payload = {
                "exchange": exchange,
                "market_type": market_type,
                "symbol": symbol,
                "interval": interval,
                "partitions": set(),
                "file_count": 0,
            }
            by_key[key] = payload
        payload["partitions"].add(partition)
        payload["file_count"] = int(payload["file_count"]) + 1

    entries: list[dict[str, object]] = []
    for key in sorted(by_key.keys()):
        raw = by_key[key]
        entries.append(
            {
                "exchange": raw["exchange"],
                "market_type": raw["market_type"],
                "symbol": raw["symbol"],
                "interval": raw["interval"],
                "partitions": sorted(str(part) for part in raw["partitions"]),
                "file_count": int(raw["file_count"]),
            }
        )
    return {
        "schema_version": "xtr_data_catalog_v1",
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "root": str(klines_root),
        "entries": entries,
    }


def _write_data_catalog(*, data_root: Path, catalog: dict[str, object]) -> Path:
    output_path = data_root / "klines" / "_catalog.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _find_market_type_candidates(
    *,
    catalog: dict[str, object],
    exchange: str,
    symbol: str,
    interval: str,
) -> list[str]:
    candidates: set[str] = set()
    for item in list(catalog.get("entries") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("exchange", "")).lower() != str(exchange).lower():
            continue
        if str(item.get("symbol", "")).upper() != str(symbol).upper():
            continue
        if str(item.get("interval", "")).lower() != str(interval).lower():
            continue
        market_type = str(item.get("market_type", "")).lower()
        if market_type:
            candidates.add(market_type)
    return sorted(candidates)


def _resolve_market_type(
    *,
    requested_market_type: str,
    catalog: dict[str, object],
    exchange: str,
    symbol: str,
    interval: str,
) -> str:
    requested = str(requested_market_type).strip().lower()
    candidates = _find_market_type_candidates(
        catalog=catalog,
        exchange=exchange,
        symbol=symbol,
        interval=interval,
    )
    if requested in {"", "auto"}:
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise FileNotFoundError(
                f"no local bars found for {exchange}.{symbol}.{interval}; "
                "please check data root or set --market-type explicitly"
            )
        raise ValueError(
            "market_type=auto is ambiguous, available candidates for "
            f"{exchange}.{symbol}.{interval}: {', '.join(candidates)}"
        )

    if requested in candidates:
        return requested

    if len(candidates) == 1:
        resolved = candidates[0]
        print(
            f"[warn] requested market_type={requested} not found for "
            f"{exchange}.{symbol}.{interval}; fallback to {resolved}",
            file=sys.stderr,
        )
        return resolved

    if not candidates:
        raise FileNotFoundError(
            f"requested market_type={requested} has no local bars for "
            f"{exchange}.{symbol}.{interval}"
        )
    raise ValueError(
        f"requested market_type={requested} not found; available candidates for "
        f"{exchange}.{symbol}.{interval}: {', '.join(candidates)}"
    )


def _resample_from_base(
    *,
    base_bars: pd.DataFrame,
    base_timeframe: str,
    target_timeframe: str,
) -> pd.DataFrame:
    base_tf = str(base_timeframe).strip().lower()
    target_tf = str(target_timeframe).strip().lower()
    if target_tf == base_tf:
        return base_bars.copy(deep=True).reset_index(drop=True)

    base_ms = _timeframe_to_ms(base_tf)
    target_ms = _timeframe_to_ms(target_tf)
    if target_ms < base_ms:
        raise ValueError(
            f"target timeframe {target_tf} is finer than base timeframe {base_tf}; "
            "cannot reconstruct lower timeframe from base bars"
        )
    if target_ms % base_ms != 0:
        raise ValueError(
            f"target timeframe {target_tf} is not an integer multiple of base timeframe {base_tf}; "
            "resample alignment is undefined"
        )

    rule = _timeframe_to_rule(target_tf)
    frames: list[pd.DataFrame] = []
    for symbol, group in base_bars.groupby("symbol", sort=True):
        source = group.sort_values("timestamp").set_index("timestamp")
        aggregated = (
            source[["open", "high", "low", "close", "volume", "funding_rate"]]
            .resample(rule, label="right", closed="right")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                    "funding_rate": "last",
                }
            )
            .dropna(subset=["open", "high", "low", "close", "volume"])
            .reset_index()
        )
        if aggregated.empty:
            continue
        aggregated["symbol"] = str(symbol).upper()
        frames.append(aggregated[list(_BAR_COLUMNS)])

    if not frames:
        raise ValueError(f"resample produced no bars for timeframe={target_tf}")
    output = pd.concat(frames, ignore_index=True)
    output = output.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    return output[list(_BAR_COLUMNS)]


class _ProfileActionRuntimeAdapter(BaseActionStrategy):
    """Inject account_context into RuntimeCore-generated strategy context."""

    def __init__(self, *, profile_config: Path, account_context: dict[str, float | int]) -> None:
        self._delegate = ProfileActionStrategy(profile_config=profile_config)
        self._account_context = dict(account_context)

    def spec(self) -> StrategySpec:
        return self._delegate.spec()

    def generate_actions(self, context: StrategyContext) -> ActionStrategyResult:
        merged_meta = dict(context.meta or {})
        merged_meta["account_context"] = dict(self._account_context)
        patched = StrategyContext(
            as_of_time=context.as_of_time,
            universe=context.universe,
            inputs=context.inputs,
            params=context.params,
            meta=merged_meta,
        )
        return self._delegate.generate_actions(patched)


def _build_runtime_config(
    *,
    strategy_id: str,
    execution_timeframe: str,
    timeframes: list[str],
) -> dict[str, object]:
    normalized_timeframes = _sorted_timeframes([*timeframes, execution_timeframe])
    return {
        "schema_version": "xtr_runtime_v1",
        "strategy_id": str(strategy_id),
        "execution_timeframe": str(execution_timeframe),
        "timeframes": normalized_timeframes,
        "indicator_plan_by_tf": {tf: [] for tf in normalized_timeframes},
        "signal_rules": {},
        "risk_rules": {
            "position_size": {"mode": "fixed_fraction", "value": 0.1},
            "stop_loss": {"mode": "atr_multiple", "n": 14, "k": 2.0},
            "take_profit": {"mode": "rr_multiple", "rr": 2.0},
        },
        "warn_policy": "record_only",
        "metadata": {
            "mode": "profile_action_smoke",
            "generated_by": "run_profile_action_backtest_smoke.py",
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        default="configs/strategy-profiles/five_min_regime_momentum/v0.3.json",
        help="StrategyProfile JSON path",
    )
    parser.add_argument("--exchange", default="bitget")
    parser.add_argument("--market-type", default="auto")
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
    parser.add_argument(
        "--persist-data-catalog",
        action="store_true",
        help="persist scanned data catalog to data/klines/_catalog.json",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    symbol = str(args.symbol).upper()
    exchange = str(args.exchange).lower()
    base_interval = str(args.interval).lower()
    _timeframe_to_ms(base_interval)
    start = _parse_time(str(args.start))
    end = _parse_time(str(args.end))
    if start >= end:
        raise ValueError("start must be before end")

    profile_path = Path(args.profile)
    precompile = StrategyProfilePrecompileEngine().compile(profile_path)
    if precompile.status != "SUCCESS":
        raise ValueError(
            "XTRSP007::PROFILE_PRECOMPILE_FAILED::"
            f"{precompile.error_code}::{precompile.error_path}::{precompile.error_message}"
        )

    resolved_profile = dict(precompile.resolved_profile)
    regime_spec = dict(resolved_profile["regime_spec"])
    execution_timeframe = str(regime_spec["decision_timeframe"]).strip().lower()
    required_timeframes = _sorted_timeframes(
        [*precompile.required_indicator_plan_by_tf.keys(), execution_timeframe]
    )
    execution_ms = _timeframe_to_ms(execution_timeframe)
    base_ms = _timeframe_to_ms(base_interval)
    if execution_ms < base_ms:
        raise ValueError(
            f"decision_timeframe={execution_timeframe} is finer than base interval={base_interval}; "
            "please provide finer base bars"
        )

    data_root = Path(args.data_root)
    data_catalog = _scan_data_catalog(data_root=data_root)
    data_catalog_path: Path | None = None
    if bool(args.persist_data_catalog):
        data_catalog_path = _write_data_catalog(data_root=data_root, catalog=data_catalog)
    market_type = _resolve_market_type(
        requested_market_type=str(args.market_type),
        catalog=data_catalog,
        exchange=exchange,
        symbol=symbol,
        interval=base_interval,
    )

    base_bars = _load_bars(
        data_root=data_root,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        interval=base_interval,
        start=start,
        end=end,
    )
    if base_bars.empty:
        raise RuntimeError("loaded bars is empty")

    bars_by_timeframe: dict[str, pd.DataFrame] = {}
    for timeframe in required_timeframes:
        bars_by_timeframe[timeframe] = _resample_from_base(
            base_bars=base_bars,
            base_timeframe=base_interval,
            target_timeframe=timeframe,
        )

    backtest_config = EventDrivenBacktestConfig(
        symbol=symbol,
        interval_ms=int(execution_ms),
        execution_lag_bars=1,
        taker_fee_bps=float(args.taker_fee_bps),
        maker_fee_bps=float(args.maker_fee_bps),
        slippage_bps=float(args.slippage_bps),
        initial_equity=float(args.initial_equity),
    )

    runtime_config = _build_runtime_config(
        strategy_id=str(resolved_profile["strategy_id"]),
        execution_timeframe=execution_timeframe,
        timeframes=required_timeframes,
    )
    report_root = build_strategy_report_root(
        strategy_name="Profile Action",
        report_base=Path(args.report_base),
        run_id=str(args.run_id).strip() or None,
        run_suffix=str(args.run_suffix),
    )
    strategy = _ProfileActionRuntimeAdapter(
        profile_config=profile_path,
        account_context={
            "equity": float(args.account_equity),
            "daily_pnl_pct": float(args.daily_pnl_pct),
            "open_positions": int(args.open_positions),
        },
    )
    runtime_result = RuntimeCore().run(
        config=runtime_config,
        data_source={
            "strategy": strategy,
            "bars_by_timeframe": bars_by_timeframe,
            "strategy_inputs": bars_by_timeframe,
            "backtest_config": backtest_config,
            "run_root": report_root,
            "warn_policy": "record_only",
            "metadata": {
                "profile_path": str(profile_path),
                "symbol": symbol,
                "market_type": market_type,
            },
        },
        mode="backtest",
    )
    if runtime_result.status not in {"SUCCESS", "PARTIAL_SUCCESS"}:
        payload = {
            "status": runtime_result.status,
            "profile": str(profile_path),
            "symbol": symbol,
            "market_type_requested": str(args.market_type),
            "market_type_resolved": market_type,
            "base_interval": base_interval,
            "execution_timeframe": execution_timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "error_code": runtime_result.error_code,
            "error_message": runtime_result.error_message,
            "artifacts": {
                "report_root": runtime_result.artifacts_root,
                "manifest_path": runtime_result.manifest_path,
                "summary_path": runtime_result.summary_path,
                "data_catalog_path": str(data_catalog_path) if data_catalog_path is not None else None,
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    backtest_outputs = dict(runtime_result.outputs.get("backtest_outputs") or {})
    summary_path = Path(str(backtest_outputs.get("summary_path") or runtime_result.summary_path))
    trades_path = Path(str(backtest_outputs.get("trades_parquet_path") or ""))
    action_snapshot_path = Path(str(backtest_outputs.get("action_snapshot_path") or ""))
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    trades_count = 0
    actions_count = 0
    if trades_path.exists():
        trades_count = int(len(pd.read_parquet(trades_path).index))
    if action_snapshot_path.exists():
        actions_count = int(len(pd.read_parquet(action_snapshot_path).index))

    payload = {
        "status": runtime_result.status,
        "profile": str(profile_path),
        "symbol": symbol,
        "market_type_requested": str(args.market_type),
        "market_type_resolved": market_type,
        "base_interval": base_interval,
        "execution_timeframe": execution_timeframe,
        "required_timeframes": required_timeframes,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": {
            "bars_by_timeframe": {
                tf: int(len(frame.index))
                for tf, frame in sorted(bars_by_timeframe.items(), key=lambda item: _timeframe_to_ms(item[0]))
            },
            "actions": actions_count,
            "trades": trades_count,
        },
        "summary": summary_payload,
        "artifacts": {
            "report_root": runtime_result.artifacts_root,
            "summary_path": str(summary_path),
            "diagnostics_path": backtest_outputs.get("diagnostics_path"),
            "trades_path": backtest_outputs.get("trades_parquet_path"),
            "equity_curve_path": backtest_outputs.get("equity_curve_parquet_path"),
            "signal_execution_path": backtest_outputs.get("signal_execution_path"),
            "decision_trace_path": backtest_outputs.get("decision_trace_path"),
            "run_manifest_path": backtest_outputs.get("run_manifest_path") or runtime_result.manifest_path,
            "data_catalog_path": str(data_catalog_path) if data_catalog_path is not None else None,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
