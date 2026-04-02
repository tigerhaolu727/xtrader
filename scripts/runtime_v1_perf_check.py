"""Runtime v1 performance and stability check for XTR-019 M5."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from xtrader.backtests import EventDrivenBacktestConfig
from xtrader.runtime import RuntimeCore
from xtrader.strategies import (
    ActionStrategyResult,
    BaseActionStrategy,
    DEFAULT_ACTION_OUTPUT_SCHEMA,
    StrategyContext,
    StrategySpec,
    TradeAction,
)


def _code_version() -> str:
    return "git:0123456789abcdef0123456789abcdef01234567"


def _interval_rule(timeframe: str) -> str:
    mapping = {
        "15m": "15min",
        "1h": "1h",
        "4h": "4h",
    }
    key = str(timeframe).strip().lower()
    if key not in mapping:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return mapping[key]


def build_bars_15m(days: int, *, symbol: str = "BTCUSDT") -> pd.DataFrame:
    rows = max(4, days * 24 * 4)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=15 * idx) for idx in range(rows)]
    close_values = [100.0 + (idx * 0.05) + (((idx // 48) % 2) * 1.2) for idx in range(rows)]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * rows,
            "open": [value - 0.08 for value in close_values],
            "high": [value + 0.16 for value in close_values],
            "low": [value - 0.2 for value in close_values],
            "close": close_values,
            "volume": [1000.0 + (idx % 11) * 20.0 for idx in range(rows)],
            "funding_rate": [0.0] * rows,
        }
    )
    return frame


def resample_ohlc(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe == "15m":
        return frame.copy().reset_index(drop=True)
    source = frame.copy().set_index("timestamp")
    grouped = (
        source[["open", "high", "low", "close", "volume", "funding_rate"]]
        .resample(_interval_rule(timeframe), label="right", closed="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "funding_rate": "mean",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    grouped["symbol"] = str(frame["symbol"].iloc[0]).upper()
    return grouped[["timestamp", "symbol", "open", "high", "low", "close", "volume", "funding_rate"]].reset_index(drop=True)


def build_runtime_config(*, scenario_count: int) -> dict[str, Any]:
    config: dict[str, Any] = {
        "schema_version": "xtr_runtime_v1",
        "strategy_id": "runtime_perf_check_v1",
        "execution_timeframe": "15m",
        "timeframes": ["15m", "1h", "4h"],
        "indicator_plan_by_tf": {
            "15m": [
                {"family": "ema", "instance_id": "ema_fast", "params": {"period": 8}},
                {"family": "ema", "instance_id": "ema_slow", "params": {"period": 21}},
            ],
            "1h": [
                {"family": "ema", "instance_id": "ema_trend_1h", "params": {"period": 34}},
            ],
            "4h": [
                {"family": "ema", "instance_id": "ema_trend_4h", "params": {"period": 55}},
            ],
        },
        "signal_rules": {"entry": {"mode": "simple"}},
        "risk_rules": {
            "position_size": {"mode": "fixed_fraction", "value": 0.1},
            "stop_loss": {"mode": "atr_multiple", "n": 14, "k": 2.0},
            "take_profit": {"mode": "rr_multiple", "rr": 2.0},
        },
    }
    if scenario_count <= 1:
        return config

    scenarios: list[dict[str, Any]] = []
    for idx in range(scenario_count):
        trial_id = f"trial_{idx+1:02d}"
        period = 8 + idx
        scenarios.append(
            {
                "trial_id": trial_id,
                "changes": [
                    {
                        "timeframe": "15m",
                        "instance_id": "ema_fast",
                        "params": {"period": period},
                    }
                ],
            }
        )
    config["trial_config"] = {
        "mode": "scenarios",
        "scenarios": scenarios,
    }
    return config


@dataclass(slots=True)
class CloseTrendStrategy(BaseActionStrategy):
    strategy_id: str = "close_trend_action"
    version: str = "v1"
    input_name: str = "features"

    def spec(self) -> StrategySpec:
        return StrategySpec(
            strategy_id=self.strategy_id,
            version=self.version,
            required_inputs=(self.input_name,),
            output_schema=DEFAULT_ACTION_OUTPUT_SCHEMA,
            params_schema={},
        )

    def generate_actions(self, context: StrategyContext) -> ActionStrategyResult:
        features = context.require_input(self.input_name).copy()
        required = {"timestamp", "symbol", "close"}
        if not required.issubset(features.columns):
            missing = ",".join(sorted(required.difference(features.columns)))
            raise ValueError(f"missing columns for strategy inputs: {missing}")

        frame = features[["timestamp", "symbol", "close"]].copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["timestamp", "symbol", "close"]).sort_values("timestamp").reset_index(drop=True)
        frame["ma"] = frame["close"].rolling(window=5, min_periods=2).mean().fillna(frame["close"])

        in_position = False
        rows: list[dict[str, object]] = []
        for row in frame.itertuples(index=False):
            close = float(row.close)
            moving = float(row.ma)
            if (not in_position) and close > moving:
                action = TradeAction.ENTER_LONG.value
                size = 1.0
                in_position = True
                reason = "entry_trend_up"
            elif in_position and close < moving:
                action = TradeAction.EXIT.value
                size = 0.0
                in_position = False
                reason = "exit_trend_down"
            else:
                action = TradeAction.HOLD.value
                size = 0.0
                reason = "hold_no_change"
            rows.append(
                {
                    "timestamp": row.timestamp,
                    "symbol": row.symbol,
                    "action": action,
                    "size": size,
                    "stop_loss": close * 0.98,
                    "take_profit": close * 1.02,
                    "reason": reason,
                }
            )

        actions = pd.DataFrame(
            rows,
            columns=["timestamp", "symbol", "action", "size", "stop_loss", "take_profit", "reason"],
        )
        result = ActionStrategyResult(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            actions=actions,
        )
        result.validate_schema(self.spec().output_schema)
        return result


def run_case(
    *,
    name: str,
    days: int,
    trials: int,
    output_root: Path,
) -> dict[str, Any]:
    bars_15m = build_bars_15m(days=days)
    bars_1h = resample_ohlc(bars_15m, "1h")
    bars_4h = resample_ohlc(bars_15m, "4h")
    config = build_runtime_config(scenario_count=trials)
    run_root = output_root / name

    core = RuntimeCore()
    result = core.run(
        config=config,
        data_source={
            "strategy": CloseTrendStrategy(),
            "bars_by_timeframe": {
                "15m": bars_15m,
                "1h": bars_1h,
                "4h": bars_4h,
            },
            "run_root": run_root,
            "code_version": _code_version(),
            "backtest_config": EventDrivenBacktestConfig(
                symbol="BTCUSDT",
                interval_ms=900_000,
                execution_lag_bars=1,
                taker_fee_bps=0.0,
                slippage_bps=0.0,
                initial_equity=1000.0,
            ),
        },
        mode="backtest",
    )
    manifest_path = run_root / "run_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"run_manifest not found for case={name}: status={result.status} code={result.error_code}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    perf = dict(manifest.get("performance_log", {}))
    case_report = {
        "name": name,
        "status": str(result.status),
        "run_root": str(run_root),
        "manifest_path": str(manifest_path),
        "elapsed_ms": int(perf.get("elapsed_ms", 0) or 0),
        "peak_rss_mb": float(perf.get("peak_rss_mb", 0.0) or 0.0),
        "trials_count": int(perf.get("trials_count", 0) or 0),
        "bars_count": int(perf.get("bars_count", 0) or 0),
        "config_hash": str(manifest.get("config_hash", "")),
        "catalog_hash": str(manifest.get("catalog_hash", "")),
        "data_version": str(manifest.get("data_version", "")),
    }
    return case_report


def evaluate_thresholds(*, case_a: dict[str, Any], case_b: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    a_pass = case_a["elapsed_ms"] <= 60_000 and case_a["peak_rss_mb"] <= 2048.0
    b_pass = case_b["elapsed_ms"] <= 600_000 and case_b["peak_rss_mb"] <= 6144.0
    regression: dict[str, Any] = {"status": "NO_BASELINE", "within_20pct": None}
    if baseline is not None:
        base_a = baseline.get("case_a", {})
        base_b = baseline.get("case_b", {})
        ratios: list[float] = []
        for current, base in ((case_a, base_a), (case_b, base_b)):
            base_elapsed = float(base.get("elapsed_ms", 0.0) or 0.0)
            if base_elapsed <= 0:
                continue
            ratios.append(float(current["elapsed_ms"]) / base_elapsed)
        within = all(r <= 1.2 for r in ratios) if ratios else None
        regression = {
            "status": "CHECKED",
            "within_20pct": within,
            "elapsed_ratios": ratios,
        }
    return {
        "case_a_threshold_pass": bool(a_pass),
        "case_b_threshold_pass": bool(b_pass),
        "regression": regression,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Runtime v1 performance checks for XTR-019 M5.")
    parser.add_argument("--output-root", default="runs/perf/runtime_v1")
    parser.add_argument("--report-path", default="runs/perf/runtime_v1/perf_report.json")
    parser.add_argument("--baseline-path", default="runs/perf/runtime_v1/perf_baseline.json")
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    case_a = run_case(name="case_a_90d_1trial_3tf", days=90, trials=1, output_root=output_root)
    case_b = run_case(name="case_b_1y_10trial_3tf", days=365, trials=10, output_root=output_root)

    baseline_path = Path(args.baseline_path)
    baseline_payload: dict[str, Any] | None = None
    if baseline_path.exists():
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))

    thresholds = evaluate_thresholds(case_a=case_a, case_b=case_b, baseline=baseline_payload)
    report = {
        "version": "v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_a": case_a,
        "case_b": case_b,
        "thresholds": thresholds,
    }
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.write_baseline:
        baseline_payload = {
            "version": "v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "case_a": case_a,
            "case_b": case_b,
        }
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"report_path: {report_path}")
    print(f"case_a_elapsed_ms: {case_a['elapsed_ms']}")
    print(f"case_a_peak_rss_mb: {case_a['peak_rss_mb']}")
    print(f"case_b_elapsed_ms: {case_b['elapsed_ms']}")
    print(f"case_b_peak_rss_mb: {case_b['peak_rss_mb']}")
    print(f"threshold_case_a_pass: {thresholds['case_a_threshold_pass']}")
    print(f"threshold_case_b_pass: {thresholds['case_b_threshold_pass']}")
    print(f"regression_status: {thresholds['regression']['status']}")
    print(f"regression_within_20pct: {thresholds['regression']['within_20pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
