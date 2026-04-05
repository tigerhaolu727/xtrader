"""Evaluate whether score_total is monotonic with outcome quality.

Usage example:
PYTHONPATH=src python scripts/check_score_effectiveness.py \
  --run-root reports/backtests/strategy/profile_action/<run_id> \
  --profile configs/strategy-profiles/ai_multi_tf_signal_v1/v0.3_score_only_p80.json \
  --horizons 12,24,48 \
  --bins 5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.pipeline import FeaturePipeline
from xtrader.strategy_profiles import RegimeScoringEngine, StrategyProfilePrecompileEngine


def _parse_horizons(raw: str) -> list[int]:
    items = [part.strip() for part in str(raw).split(",")]
    out: list[int] = []
    for item in items:
        if not item:
            continue
        value = int(item)
        if value <= 0:
            raise ValueError(f"horizon must be positive: {value}")
        out.append(value)
    if not out:
        raise ValueError("horizons cannot be empty")
    return sorted(set(out))


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy(deep=True)
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out["symbol"] = out["symbol"].astype(str).str.upper()
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "funding_rate" not in out.columns:
        out["funding_rate"] = 0.0
    out["funding_rate"] = pd.to_numeric(out["funding_rate"], errors="coerce").fillna(0.0)
    out = (
        out.dropna(subset=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        .sort_values(["timestamp", "symbol"])
        .drop_duplicates(subset=["timestamp", "symbol"], keep="last")
        .reset_index(drop=True)
    )
    return out


def _load_bars_by_timeframe(*, run_root: Path, required_timeframes: list[str]) -> dict[str, pd.DataFrame]:
    bars_by_tf: dict[str, pd.DataFrame] = {}
    for timeframe in required_timeframes:
        tf = str(timeframe).strip().lower()
        candidates = [
            run_root / "snapshots" / "base" / f"price_{tf}.parquet",
            run_root / "snapshots" / "resampled" / f"price_{tf}.parquet",
        ]
        selected: Path | None = None
        for path in candidates:
            if path.exists():
                selected = path
                break
        if selected is None:
            raise FileNotFoundError(f"missing snapshot bars for timeframe={tf}, checked: {candidates}")
        bars_by_tf[tf] = _normalize_bars(pd.read_parquet(selected))
    return bars_by_tf


def _build_scoring_frame(
    *,
    profile_path: Path,
    bars_by_timeframe: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    precompile = StrategyProfilePrecompileEngine().compile(profile_path)
    if precompile.status != "SUCCESS":
        raise ValueError(
            "XTRSP007::PROFILE_PRECOMPILE_FAILED::"
            f"{precompile.error_code}::{precompile.error_path}::{precompile.error_message}"
        )
    resolved_profile = dict(precompile.resolved_profile)
    regime_spec = dict(resolved_profile["regime_spec"])
    model_df = FeaturePipeline().build_profile_model_df(
        bars_by_timeframe=bars_by_timeframe,
        required_indicator_plan_by_tf=dict(precompile.required_indicator_plan_by_tf),
        required_feature_refs=list(precompile.required_feature_refs),
        decision_timeframe=str(regime_spec["decision_timeframe"]),
        alignment_policy=dict(regime_spec["alignment_policy"]),
    )
    scoring_df = RegimeScoringEngine().run(
        resolved_profile=resolved_profile,
        resolved_input_bindings=dict(precompile.resolved_input_bindings),
        model_df=model_df,
    ).frame
    out = scoring_df[["timestamp", "symbol", "score_total", "state"]].copy(deep=True)
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out["symbol"] = out["symbol"].astype(str).str.upper()
    out["score_total"] = pd.to_numeric(out["score_total"], errors="coerce")
    return out


def _load_entries(run_root: Path) -> pd.DataFrame:
    action_input_path = run_root / "snapshots" / "action_input.parquet"
    if not action_input_path.exists():
        raise FileNotFoundError(f"missing action input snapshot: {action_input_path}")
    actions = pd.read_parquet(action_input_path)
    required_cols = {"signal_time", "execution_time", "symbol", "action"}
    missing = required_cols.difference(actions.columns)
    if missing:
        raise ValueError(f"action input missing columns: {sorted(missing)}")
    out = actions.copy(deep=True)
    out["signal_time"] = pd.to_datetime(out["signal_time"], utc=True, errors="coerce")
    out["execution_time"] = pd.to_datetime(out["execution_time"], utc=True, errors="coerce")
    out["symbol"] = out["symbol"].astype(str).str.upper()
    if "status" in out.columns:
        out = out[out["status"].astype(str).str.upper() == "FILLED"].copy(deep=True)
    out = out[out["action"].astype(str).isin(["ENTER_LONG", "ENTER_SHORT"])].copy(deep=True)
    out["side"] = np.where(out["action"].astype(str) == "ENTER_LONG", "LONG", "SHORT")
    out = out.dropna(subset=["signal_time", "execution_time"]).reset_index(drop=True)
    return out


def _load_trades(run_root: Path) -> pd.DataFrame:
    trades_path = run_root / "ledgers" / "trades.parquet"
    if not trades_path.exists():
        raise FileNotFoundError(f"missing trades ledger: {trades_path}")
    trades = pd.read_parquet(trades_path).copy(deep=True)
    required = {"symbol", "side", "entry_time", "net_pnl"}
    missing = required.difference(trades.columns)
    if missing:
        raise ValueError(f"trades missing columns: {sorted(missing)}")
    trades["symbol"] = trades["symbol"].astype(str).str.upper()
    trades["side"] = trades["side"].astype(str).str.upper()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True, errors="coerce")
    trades["net_pnl"] = pd.to_numeric(trades["net_pnl"], errors="coerce")
    keep = ["symbol", "side", "entry_time", "net_pnl"]
    if "exit_reason" in trades.columns:
        keep.append("exit_reason")
    trades = trades[keep].dropna(subset=["symbol", "side", "entry_time"]).copy(deep=True)
    dup_counts = trades.groupby(["symbol", "side", "entry_time"]).size().reset_index(name="trade_count")
    trades = (
        trades.sort_values(["entry_time"])
        .drop_duplicates(subset=["symbol", "side", "entry_time"], keep="first")
        .merge(dup_counts, on=["symbol", "side", "entry_time"], how="left")
    )
    return trades.reset_index(drop=True)


def _attach_forward_returns(
    *,
    entries: pd.DataFrame,
    base_bars: pd.DataFrame,
    horizons: list[int],
) -> pd.DataFrame:
    out = entries.copy(deep=True)
    base = base_bars[["timestamp", "symbol", "close"]].copy(deep=True)
    base["timestamp"] = pd.to_datetime(base["timestamp"], utc=True, errors="coerce")
    base["symbol"] = base["symbol"].astype(str).str.upper()
    base["close"] = pd.to_numeric(base["close"], errors="coerce")
    base = base.dropna(subset=["timestamp", "symbol", "close"]).sort_values(["symbol", "timestamp"])
    for h in horizons:
        col_future = f"close_future_h{h}"
        temp = base.copy(deep=True)
        temp[col_future] = temp.groupby("symbol", sort=False)["close"].shift(-h)
        out = out.merge(
            temp[["timestamp", "symbol", "close", col_future]],
            left_on=["execution_time", "symbol"],
            right_on=["timestamp", "symbol"],
            how="left",
            suffixes=("", f"_h{h}"),
        )
        out = out.drop(columns=["timestamp"], errors="ignore")
        raw = (pd.to_numeric(out[col_future], errors="coerce") / pd.to_numeric(out["close"], errors="coerce")) - 1.0
        out[f"fwd_ret_h{h}"] = np.where(out["side"] == "LONG", raw, -raw)
        out = out.drop(columns=[col_future, "close"], errors="ignore")
    return out


def _monotonic_non_decreasing(values: list[float]) -> bool:
    clean = [v for v in values if pd.notna(v)]
    if len(clean) <= 1:
        return True
    return all(cur >= prev for prev, cur in zip(clean[:-1], clean[1:]))


def _evaluate_side(
    *,
    frame: pd.DataFrame,
    side: str,
    bins: int,
    horizons: list[int],
) -> tuple[dict[str, Any], pd.DataFrame]:
    local = frame[frame["side"] == side].copy(deep=True)
    if local.empty:
        return {"side": side, "error": "no samples"}, pd.DataFrame()

    local["confidence"] = local["score_total"] if side == "LONG" else -local["score_total"]
    local = local.dropna(subset=["confidence"])
    if local.empty:
        return {"side": side, "error": "no confidence values"}, pd.DataFrame()

    effective_bins = min(int(bins), int(local["confidence"].nunique()))
    if effective_bins < 2:
        return {"side": side, "error": "insufficient unique confidence values"}, pd.DataFrame()

    local["bucket"] = pd.qcut(local["confidence"], q=effective_bins, duplicates="drop")
    grouped = local.groupby("bucket", observed=False)
    report = grouped.agg(
        sample_count=("confidence", "size"),
        conf_min=("confidence", "min"),
        conf_max=("confidence", "max"),
        conf_mean=("confidence", "mean"),
        trade_count=("net_pnl", lambda x: int(pd.to_numeric(x, errors="coerce").notna().sum())),
        trade_win_rate=("net_pnl", lambda x: float((pd.to_numeric(x, errors="coerce") > 0).mean())),
        trade_avg_pnl=("net_pnl", lambda x: float(pd.to_numeric(x, errors="coerce").mean())),
        trade_median_pnl=("net_pnl", lambda x: float(pd.to_numeric(x, errors="coerce").median())),
    ).reset_index()
    report["bucket"] = report["bucket"].astype(str)

    for h in horizons:
        col = f"fwd_ret_h{h}"
        agg = grouped[col].agg(["count", "mean", "median"]).reset_index()
        agg["win_rate"] = grouped[col].apply(lambda x: float((pd.to_numeric(x, errors="coerce") > 0).mean())).values
        report[f"fwd_h{h}_count"] = agg["count"].to_numpy()
        report[f"fwd_h{h}_win_rate"] = agg["win_rate"].to_numpy()
        report[f"fwd_h{h}_mean"] = agg["mean"].to_numpy()
        report[f"fwd_h{h}_median"] = agg["median"].to_numpy()

    local_trade = local.dropna(subset=["net_pnl"])
    corr_trade = float(local_trade["confidence"].corr(local_trade["net_pnl"], method="spearman")) if not local_trade.empty else float("nan")
    corr_forward: dict[str, float] = {}
    for h in horizons:
        col = f"fwd_ret_h{h}"
        tmp = local.dropna(subset=[col])
        corr_forward[f"h{h}"] = (
            float(tmp["confidence"].corr(tmp[col], method="spearman"))
            if not tmp.empty
            else float("nan")
        )

    side_summary = {
        "side": side,
        "sample_count": int(len(local.index)),
        "bucket_count": int(len(report.index)),
        "spearman_trade_pnl": corr_trade,
        "spearman_forward_ret": corr_forward,
        "monotonic_trade_win_rate": _monotonic_non_decreasing(report["trade_win_rate"].tolist()),
        "monotonic_trade_avg_pnl": _monotonic_non_decreasing(report["trade_avg_pnl"].tolist()),
    }
    for h in horizons:
        key = f"fwd_h{h}_win_rate"
        side_summary[f"monotonic_{key}"] = _monotonic_non_decreasing(report[key].tolist())
    return side_summary, report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, help="Backtest output root path")
    parser.add_argument("--profile", required=True, help="Strategy profile JSON path")
    parser.add_argument("--horizons", default="12,24,48", help="Forward return horizons in bars, comma separated")
    parser.add_argument("--bins", type=int, default=5, help="Quantile bins for confidence bucket")
    parser.add_argument("--out-dir", default="", help="Optional directory to write analysis artifacts")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    run_root = Path(args.run_root)
    profile_path = Path(args.profile)
    horizons = _parse_horizons(args.horizons)
    bins = int(args.bins)
    if bins < 2:
        raise ValueError("bins must be >= 2")

    precompile = StrategyProfilePrecompileEngine().compile(profile_path)
    if precompile.status != "SUCCESS":
        raise ValueError(
            "XTRSP007::PROFILE_PRECOMPILE_FAILED::"
            f"{precompile.error_code}::{precompile.error_path}::{precompile.error_message}"
        )
    required_tfs = sorted(str(tf) for tf in precompile.required_indicator_plan_by_tf.keys())
    bars_by_tf = _load_bars_by_timeframe(run_root=run_root, required_timeframes=required_tfs)
    scoring = _build_scoring_frame(profile_path=profile_path, bars_by_timeframe=bars_by_tf)

    entries = _load_entries(run_root)
    entries = entries.merge(
        scoring[["timestamp", "symbol", "score_total"]],
        left_on=["signal_time", "symbol"],
        right_on=["timestamp", "symbol"],
        how="left",
    ).drop(columns=["timestamp"], errors="ignore")

    trades = _load_trades(run_root)
    entries = entries.merge(
        trades,
        left_on=["symbol", "side", "execution_time"],
        right_on=["symbol", "side", "entry_time"],
        how="left",
    ).drop(columns=["entry_time"], errors="ignore")

    decision_tf = str(dict(precompile.resolved_profile["regime_spec"])["decision_timeframe"]).strip().lower()
    if decision_tf not in bars_by_tf:
        raise ValueError(f"decision timeframe bars missing in snapshots: {decision_tf}")
    entries = _attach_forward_returns(entries=entries, base_bars=bars_by_tf[decision_tf], horizons=horizons)

    long_summary, long_table = _evaluate_side(frame=entries, side="LONG", bins=bins, horizons=horizons)
    short_summary, short_table = _evaluate_side(frame=entries, side="SHORT", bins=bins, horizons=horizons)

    output = {
        "run_root": str(run_root),
        "profile": str(profile_path),
        "horizons": horizons,
        "bins": bins,
        "rows": {
            "entries_total": int(len(entries.index)),
            "long_entries": int((entries["side"] == "LONG").sum()),
            "short_entries": int((entries["side"] == "SHORT").sum()),
            "entries_with_score": int(pd.to_numeric(entries["score_total"], errors="coerce").notna().sum()),
            "entries_with_trade": int(pd.to_numeric(entries["net_pnl"], errors="coerce").notna().sum()),
        },
        "summary": {
            "long": long_summary,
            "short": short_summary,
        },
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    print("\n[LONG BUCKETS]")
    if long_table.empty:
        print("<empty>")
    else:
        print(long_table.to_string(index=False))
    print("\n[SHORT BUCKETS]")
    if short_table.empty:
        print("<empty>")
    else:
        print(short_table.to_string(index=False))

    out_dir_raw = str(args.out_dir).strip()
    if out_dir_raw:
        out_dir = Path(out_dir_raw)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "score_effectiveness_summary.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        long_table.to_csv(out_dir / "score_effectiveness_long.csv", index=False)
        short_table.to_csv(out_dir / "score_effectiveness_short.csv", index=False)
        entries.to_parquet(out_dir / "score_effectiveness_entries.parquet", index=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
