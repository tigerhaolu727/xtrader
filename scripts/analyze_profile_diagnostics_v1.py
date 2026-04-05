"""Analyze profile backtest diagnostics from existing run artifacts.

This script does not modify runtime/main strategy code. It only reads artifacts:
- summary.json
- timelines/signal_execution.parquet
- timelines/decision_trace.parquet
- snapshots/action_input.parquet
- ledgers/trades.parquet

Usage example:
PYTHONPATH=src python scripts/analyze_profile_diagnostics_v1.py
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_RUNS: dict[str, str] = {
    "v0.3_score_only_p80": "reports/backtests/strategy/profile_action/20260404T125010Z_profile_action_ai_multi_tf_v03_score_only_p80_2025",
    "v0.4_minpack_gate_draft": "reports/backtests/strategy/profile_action/20260404T121008Z_profile_action_ai_multi_tf_v04_minpack_gate_2025",
    "v0.2_strong_only": "reports/backtests/strategy/profile_action/20260404T134239Z_profile_action_ai_multi_tf_v02_strong_only_2025",
    "v0.2_no_aggressive": "reports/backtests/strategy/profile_action/20260404T135518Z_profile_action_ai_multi_tf_v02_no_aggressive_2025",
    "v0.5_minpack_gate_2of3": "reports/backtests/strategy/profile_action/20260404T143637Z_profile_action_ai_multi_tf_v05_minpack_gate_2of3_2025",
}


@dataclass(frozen=True)
class RunInput:
    profile_id: str
    run_root: Path


def _parse_run_item(text: str) -> RunInput:
    raw = str(text).strip()
    if "=" not in raw:
        raise ValueError(f"--run must be profile_id=path: {raw}")
    profile_id, run_root = raw.split("=", 1)
    profile_id = profile_id.strip()
    if not profile_id:
        raise ValueError(f"empty profile_id in --run: {raw}")
    path = Path(run_root.strip())
    return RunInput(profile_id=profile_id, run_root=path)


def _to_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _parse_json_obj(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _load_summary(run_root: Path) -> dict[str, Any]:
    path = run_root / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"missing summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_signal_execution(run_root: Path) -> pd.DataFrame:
    path = run_root / "timelines" / "signal_execution.parquet"
    if not path.exists():
        raise FileNotFoundError(f"missing signal_execution: {path}")
    frame = pd.read_parquet(path).copy(deep=True)
    for col in ("signal_time", "execution_time"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], utc=True, errors="coerce")
    if "symbol" in frame.columns:
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
    if "action" in frame.columns:
        frame["action"] = frame["action"].astype(str)
    return frame


def _load_decision_trace(run_root: Path) -> pd.DataFrame:
    path = run_root / "timelines" / "decision_trace.parquet"
    if not path.exists():
        raise FileNotFoundError(f"missing decision_trace: {path}")
    frame = pd.read_parquet(path).copy(deep=True)
    for col in ("signal_time", "execution_time"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], utc=True, errors="coerce")
    if "symbol" in frame.columns:
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
    if "action" in frame.columns:
        frame["action"] = frame["action"].astype(str)
    frame["score_total"] = pd.to_numeric(frame.get("score_total"), errors="coerce")
    return frame


def _load_entries_and_trades(run_root: Path) -> pd.DataFrame:
    action_input_path = run_root / "snapshots" / "action_input.parquet"
    trades_path = run_root / "ledgers" / "trades.parquet"
    if not action_input_path.exists() or not trades_path.exists():
        return pd.DataFrame()

    actions = pd.read_parquet(action_input_path).copy(deep=True)
    trades = pd.read_parquet(trades_path).copy(deep=True)

    for col in ("signal_time", "execution_time"):
        if col in actions.columns:
            actions[col] = pd.to_datetime(actions[col], utc=True, errors="coerce")
    actions["symbol"] = actions.get("symbol", "").astype(str).str.upper()
    actions["action"] = actions.get("action", "").astype(str)
    actions["status"] = actions.get("status", "").astype(str).str.upper()
    entries = actions[
        (actions["status"] == "FILLED") & (actions["action"].isin(["ENTER_LONG", "ENTER_SHORT"]))
    ][["signal_time", "execution_time", "symbol", "action"]].copy(deep=True)
    if entries.empty:
        return pd.DataFrame()
    entries["side"] = np.where(entries["action"] == "ENTER_LONG", "LONG", "SHORT")

    trades["entry_time"] = pd.to_datetime(trades.get("entry_time"), utc=True, errors="coerce")
    trades["symbol"] = trades.get("symbol", "").astype(str).str.upper()
    trades["side"] = trades.get("side", "").astype(str).str.upper()
    trades["net_pnl"] = pd.to_numeric(trades.get("net_pnl"), errors="coerce")
    trade_keep = (
        trades[["symbol", "side", "entry_time", "net_pnl"]]
        .dropna(subset=["entry_time"])
        .sort_values("entry_time")
        .drop_duplicates(subset=["symbol", "side", "entry_time"], keep="first")
    )
    merged = entries.merge(
        trade_keep,
        left_on=["symbol", "side", "execution_time"],
        right_on=["symbol", "side", "entry_time"],
        how="left",
    ).drop(columns=["entry_time"], errors="ignore")
    return merged


def _score_effectiveness(entries_with_score: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if entries_with_score.empty:
        return out
    for side in ("LONG", "SHORT"):
        local = entries_with_score[entries_with_score["side"] == side].copy(deep=True)
        local = local.dropna(subset=["score_total"])
        if local.empty:
            out[f"{side.lower()}_samples"] = 0
            out[f"{side.lower()}_spearman_trade_pnl"] = float("nan")
            continue
        local["confidence"] = local["score_total"] if side == "LONG" else -local["score_total"]
        traded = local.dropna(subset=["net_pnl"])
        spearman = (
            float(traded["confidence"].corr(traded["net_pnl"], method="spearman"))
            if len(traded.index) > 1
            else float("nan")
        )
        out[f"{side.lower()}_samples"] = int(len(local.index))
        out[f"{side.lower()}_trades"] = int(len(traded.index))
        out[f"{side.lower()}_spearman_trade_pnl"] = spearman
        out[f"{side.lower()}_score_min"] = float(local["score_total"].min())
        out[f"{side.lower()}_score_p50"] = float(local["score_total"].quantile(0.5))
        out[f"{side.lower()}_score_p80"] = float(local["score_total"].quantile(0.8))
        out[f"{side.lower()}_score_max"] = float(local["score_total"].max())
    return out


def _analyze_run(run: RunInput) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    summary = _load_summary(run.run_root)
    signal_execution = _load_signal_execution(run.run_root)
    decision_trace = _load_decision_trace(run.run_root)
    entries_trades = _load_entries_and_trades(run.run_root)

    action_counts = signal_execution["action"].astype(str).value_counts().to_dict()
    action_counts = {str(k): int(v) for k, v in action_counts.items()}

    # join score_total onto entries for score effectiveness
    score_ref = (
        decision_trace[["signal_time", "symbol", "score_total"]]
        .dropna(subset=["signal_time", "symbol"])
        .drop_duplicates(subset=["signal_time", "symbol"], keep="last")
    )
    if not entries_trades.empty:
        entries_trades = entries_trades.merge(
            score_ref,
            on=["signal_time", "symbol"],
            how="left",
        )
    score_diag = _score_effectiveness(entries_trades)

    # parse gate and condition info from decision_trace json
    gate_rows: list[dict[str, Any]] = []
    condition_counter = Counter()
    condition_counter_enter = Counter()
    total_rows = int(len(decision_trace.index))
    if "action_raw" in decision_trace.columns:
        enter_mask = decision_trace["action_raw"].astype(str).isin(["ENTER_LONG", "ENTER_SHORT"])
    else:
        enter_mask = decision_trace["action"].astype(str).isin(["ENTER"])
    total_enter_rows = int(enter_mask.sum())

    for _, row in decision_trace.iterrows():
        action = str(row.get("action", ""))
        action_raw = str(row.get("action_raw", action))
        is_enter_row = action_raw in {"ENTER_LONG", "ENTER_SHORT"} or action == "ENTER"
        rule_obj = _parse_json_obj(row.get("rule_results_json"))
        signal_obj = _parse_json_obj(row.get("signal_decision_json"))

        # condition hits
        cond_hits = rule_obj.get("condition_hits")
        if isinstance(cond_hits, list):
            uniq = set(str(item) for item in cond_hits if str(item).strip())
            condition_counter.update(uniq)
            if is_enter_row:
                condition_counter_enter.update(uniq)

        # gate results
        selected_gate_id = signal_obj.get("selected_gate_id")
        gate_results = signal_obj.get("gate_results")
        if isinstance(gate_results, list):
            for item in gate_results:
                if not isinstance(item, dict):
                    continue
                gate_id = str(item.get("gate_id", "")).strip()
                if not gate_id:
                    continue
                passed = bool(item.get("passed", False))
                gate_rows.append(
                    {
                        "profile_id": run.profile_id,
                        "gate_id": gate_id,
                        "side": str(item.get("side", "")),
                        "level": str(item.get("level", "")),
                        "mode": str(item.get("mode", "")),
                        "min_hit": item.get("min_hit"),
                        "passed": passed,
                        "hit_count": int(item.get("hit_count", 0) or 0),
                        "required_count": int(item.get("required_count", 0) or 0),
                        "is_enter_row": is_enter_row,
                        "selected_on_row": bool(selected_gate_id) and str(selected_gate_id) == gate_id,
                    }
                )

    gate_df = pd.DataFrame(gate_rows)
    if gate_df.empty:
        gate_agg = pd.DataFrame(
            columns=[
                "profile_id",
                "gate_id",
                "side",
                "level",
                "mode",
                "min_hit",
                "obs_count",
                "pass_count",
                "pass_rate",
                "enter_rows",
                "selected_count",
                "selected_per_pass",
            ]
        )
    else:
        grouped = gate_df.groupby(["profile_id", "gate_id", "side", "level", "mode", "min_hit"], dropna=False)
        gate_agg = grouped.agg(
            obs_count=("passed", "size"),
            pass_count=("passed", "sum"),
            enter_rows=("is_enter_row", "sum"),
            selected_count=("selected_on_row", "sum"),
        ).reset_index()
        gate_agg["pass_rate"] = gate_agg["pass_count"] / gate_agg["obs_count"].replace(0, np.nan)
        gate_agg["selected_per_pass"] = gate_agg["selected_count"] / gate_agg["pass_count"].replace(0, np.nan)

    condition_rows = []
    all_ids = sorted(set(condition_counter.keys()).union(condition_counter_enter.keys()))
    for cond_id in all_ids:
        hit_all = int(condition_counter[cond_id])
        hit_enter = int(condition_counter_enter[cond_id])
        condition_rows.append(
            {
                "profile_id": run.profile_id,
                "condition_id": cond_id,
                "hit_count_all_rows": hit_all,
                "hit_rate_all_rows": (hit_all / total_rows) if total_rows > 0 else np.nan,
                "hit_count_enter_rows": hit_enter,
                "hit_rate_enter_rows": (hit_enter / total_enter_rows) if total_enter_rows > 0 else np.nan,
            }
        )
    condition_df = pd.DataFrame(condition_rows)

    summary_row = {
        "profile_id": run.profile_id,
        "run_root": str(run.run_root),
        "sample_count": int(summary.get("sample_count", 0)),
        "trade_count": int(summary.get("trade_count", 0)),
        "net_return": float(summary.get("net_return", 0.0)),
        "max_drawdown": float(summary.get("max_drawdown", 0.0)),
        "win_rate": float(summary.get("win_rate", 0.0)),
        "profit_factor": float(summary.get("profit_factor", 0.0)),
        "expectancy": float(summary.get("expectancy", 0.0)),
        "total_fee_cost": float(summary.get("total_fee_cost", 0.0)),
        "total_slippage_cost": float(summary.get("total_slippage_cost", 0.0)),
        "action_enter_long": int(action_counts.get("ENTER_LONG", 0)),
        "action_enter_short": int(action_counts.get("ENTER_SHORT", 0)),
        "action_exit": int(action_counts.get("EXIT", 0)),
        "action_hold": int(action_counts.get("HOLD", 0)),
        "trace_rows": total_rows,
        "trace_enter_rows": total_enter_rows,
    }
    summary_row.update(score_diag)

    return summary_row, gate_agg, condition_df


def _markdown_report(summary_df: pd.DataFrame, out_dir: Path) -> str:
    lines: list[str] = []
    lines.append("# Profile Diagnostics V1")
    lines.append("")
    lines.append(f"- generated_at: `{pd.Timestamp.utcnow().isoformat()}`")
    lines.append(f"- output_dir: `{out_dir}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    cols = [
        "profile_id",
        "trade_count",
        "net_return",
        "max_drawdown",
        "win_rate",
        "profit_factor",
        "expectancy",
        "action_enter_long",
        "action_enter_short",
    ]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for _, row in summary_df[cols].iterrows():
        vals = []
        for col in cols:
            value = row[col]
            if isinstance(value, float):
                vals.append(f"{value:.6f}")
            else:
                vals.append(str(value))
        lines.append("| " + " | ".join(vals) + " |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `summary_comparison.csv`: profile-level metric comparison.")
    lines.append("- `gate_metrics.csv`: entry_gate pass/selection effectiveness.")
    lines.append("- `condition_metrics.csv`: condition hit rates (all rows vs enter rows).")
    lines.append("- `condition_metrics_top50_enter_rate.csv`: top conditions by enter hit count.")
    lines.append("")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="profile_id=run_root; can be repeated. If omitted, use built-in 5 runs.",
    )
    parser.add_argument(
        "--out-dir",
        default="reports/analysis/profile_diagnostics_v1/latest",
        help="directory to write outputs",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.run:
        runs = [_parse_run_item(item) for item in list(args.run)]
    else:
        runs = [RunInput(profile_id=k, run_root=Path(v)) for k, v in DEFAULT_RUNS.items()]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    gate_frames: list[pd.DataFrame] = []
    condition_frames: list[pd.DataFrame] = []

    for run in runs:
        summary_row, gate_df, condition_df = _analyze_run(run)
        summary_rows.append(summary_row)
        if not gate_df.empty:
            gate_frames.append(gate_df)
        if not condition_df.empty:
            condition_frames.append(condition_df)

    summary_df = pd.DataFrame(summary_rows).sort_values("profile_id").reset_index(drop=True)
    gate_df = (
        pd.concat(gate_frames, ignore_index=True).sort_values(["profile_id", "gate_id"])
        if gate_frames
        else pd.DataFrame()
    )
    condition_df = (
        pd.concat(condition_frames, ignore_index=True).sort_values(["profile_id", "condition_id"])
        if condition_frames
        else pd.DataFrame()
    )

    summary_path = out_dir / "summary_comparison.csv"
    gates_path = out_dir / "gate_metrics.csv"
    cond_path = out_dir / "condition_metrics.csv"
    top_cond_path = out_dir / "condition_metrics_top50_enter_rate.csv"
    md_path = out_dir / "report.md"

    summary_df.to_csv(summary_path, index=False)
    if not gate_df.empty:
        gate_df.to_csv(gates_path, index=False)
    else:
        pd.DataFrame().to_csv(gates_path, index=False)
    if not condition_df.empty:
        condition_df.to_csv(cond_path, index=False)
        top_cond = (
            condition_df.sort_values(["hit_count_enter_rows", "hit_rate_enter_rows"], ascending=[False, False])
            .groupby("profile_id", as_index=False)
            .head(50)
            .reset_index(drop=True)
        )
        top_cond.to_csv(top_cond_path, index=False)
    else:
        pd.DataFrame().to_csv(cond_path, index=False)
        pd.DataFrame().to_csv(top_cond_path, index=False)

    md_path.write_text(_markdown_report(summary_df=summary_df, out_dir=out_dir), encoding="utf-8")

    payload = {
        "status": "SUCCESS",
        "runs": [{"profile_id": run.profile_id, "run_root": str(run.run_root)} for run in runs],
        "outputs": {
            "summary_comparison_csv": str(summary_path),
            "gate_metrics_csv": str(gates_path),
            "condition_metrics_csv": str(cond_path),
            "condition_top50_csv": str(top_cond_path),
            "report_md": str(md_path),
        },
        "row_counts": {
            "summary_profiles": int(len(summary_df.index)),
            "gate_rows": int(len(gate_df.index)),
            "condition_rows": int(len(condition_df.index)),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
