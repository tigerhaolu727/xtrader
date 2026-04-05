"""Analyze condition-role effectiveness and scoring validity across profile backtests.

Inputs (read-only):
- summary.json
- timelines/decision_trace.parquet
- snapshots/action_input.parquet
- ledgers/trades.parquet

Usage:
PYTHONPATH=src python scripts/analyze_profile_diagnostics_v2.py
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_RUNS: dict[str, str] = {
    "v0.2_no_aggressive": "reports/backtests/strategy/profile_action/20260404T135518Z_profile_action_ai_multi_tf_v02_no_aggressive_2025",
    "v0.2_strong_only": "reports/backtests/strategy/profile_action/20260404T134239Z_profile_action_ai_multi_tf_v02_strong_only_2025",
    "v0.3_score_only_p80": "reports/backtests/strategy/profile_action/20260404T125010Z_profile_action_ai_multi_tf_v03_score_only_p80_2025",
    "v0.4_minpack_gate_draft": "reports/backtests/strategy/profile_action/20260404T121008Z_profile_action_ai_multi_tf_v04_minpack_gate_2025",
    "v0.5_minpack_gate_2of3": "reports/backtests/strategy/profile_action/20260404T143637Z_profile_action_ai_multi_tf_v05_minpack_gate_2of3_2025",
    "v0.6_minpack_gate_mid_quality": "reports/backtests/strategy/profile_action/20260404T154446Z_profile_action_ai_multi_tf_v06_mid_quality_2025",
    "v0.7_minpack_deweight_structure": "reports/backtests/strategy/profile_action/20260404T155627Z_profile_action_ai_multi_tf_v07_deweight_structure_2025",
    "v0.8_minpack_entry_t022": "reports/backtests/strategy/profile_action/20260404T160457Z_profile_action_ai_multi_tf_v08_entry_threshold_relaxed_2025",
    "v0.9_minpack_entry_t024": "reports/backtests/strategy/profile_action/20260404T164913Z_profile_action_ai_multi_tf_v09_entry_t024_2025",
    "v0.10_minpack_entry_t023": "reports/backtests/strategy/profile_action/20260404T165810Z_profile_action_ai_multi_tf_v10_entry_t023_2025",
    "v0.11_minpack_entry_t021": "reports/backtests/strategy/profile_action/20260404T171225Z_profile_action_ai_multi_tf_v11_entry_t021_2025",
}

CONDITION_LIBRARY_PATH = Path("docs/02-strategy/discussions/indicator_condition_library_v1_baseline.csv")

# V1 baseline库未覆盖的条件补充映射
CONDITION_OVERRIDES: dict[str, dict[str, str]] = {
    "cond_4h_adx_ge_25": {"direction": "LONG", "role": "过滤", "timeframe": "4h", "indicator_family": "DMI/ADX"},
    "cond_4h_adx_ge_25_short": {"direction": "SHORT", "role": "过滤", "timeframe": "4h", "indicator_family": "DMI/ADX"},
    "cond_1h_close_break_prev_high": {"direction": "LONG", "role": "确认", "timeframe": "1h", "indicator_family": "Price+Structure"},
    "cond_1h_close_break_prev_low": {"direction": "SHORT", "role": "确认", "timeframe": "1h", "indicator_family": "Price+Structure"},
    "cond_1h_volume_zscore_ge_1": {"direction": "LONG", "role": "确认", "timeframe": "1h", "indicator_family": "Volume"},
    "cond_1h_volume_zscore_ge_1_short": {"direction": "SHORT", "role": "确认", "timeframe": "1h", "indicator_family": "Volume"},
}

DEFAULT_ROLE_BY_TF = {
    "4h": "过滤",
    "1h": "确认",
    "15m": "确认",
    "5m": "触发",
    "cross_tf": "过滤",
}


@dataclass(frozen=True)
class RunInput:
    profile_id: str
    run_root: Path


@dataclass
class RunArtifacts:
    summary: dict[str, Any]
    decision_rows: pd.DataFrame
    filled_entries: pd.DataFrame


def _parse_run_item(text: str) -> RunInput:
    raw = str(text).strip()
    if "=" not in raw:
        raise ValueError(f"--run must be profile_id=path: {raw}")
    profile_id, run_root = raw.split("=", 1)
    profile_id = profile_id.strip()
    if not profile_id:
        raise ValueError(f"empty profile_id in --run: {raw}")
    return RunInput(profile_id=profile_id, run_root=Path(run_root.strip()))


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


def _safe_win_rate(values: pd.Series) -> float:
    local = pd.to_numeric(values, errors="coerce").dropna()
    if local.empty:
        return float("nan")
    return float((local > 0).mean())


def _safe_expectancy(values: pd.Series) -> float:
    local = pd.to_numeric(values, errors="coerce").dropna()
    if local.empty:
        return float("nan")
    return float(local.mean())


def _safe_pf(values: pd.Series) -> float:
    local = pd.to_numeric(values, errors="coerce").dropna()
    if local.empty:
        return float("nan")
    gross_profit = float(local[local > 0].sum())
    gross_loss = float((-local[local < 0]).sum())
    if gross_loss <= 0:
        return float("nan")
    return gross_profit / gross_loss


def _infer_timeframe_from_condition_id(condition_id: str) -> str:
    cid = str(condition_id)
    for tf in ("4h", "1h", "15m", "5m", "cross_tf"):
        if f"cond_{tf}_" in cid or cid.startswith(f"cond_{tf}_"):
            return tf
    if cid.startswith("cond_structure_"):
        return "15m"
    return "unknown"


def _infer_direction(condition_id: str) -> str:
    cid = str(condition_id)
    if cid.endswith("_short"):
        return "SHORT"
    short_tokens = (
        "_dead_cross",
        "_bear_",
        "_gt_65",
        "_gt_70",
        "_price_lt_",
        "_lose_",
        "near_dead",
        "reject_short",
        "_not_golden_",
    )
    long_tokens = (
        "_golden_cross",
        "_bull_",
        "_lt_25",
        "_lt_30",
        "_lt_35",
        "_price_gt_",
        "reclaim",
        "near_golden",
        "reject_long",
        "_not_dead_",
    )
    if any(tok in cid for tok in short_tokens):
        return "SHORT"
    if any(tok in cid for tok in long_tokens):
        return "LONG"
    return "UNKNOWN"


def _load_condition_library(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["condition_id", "direction", "role", "timeframe", "indicator_family"])
    frame = pd.read_csv(path)
    keep = ["condition_id", "direction", "role", "timeframe", "indicator_family"]
    for col in keep:
        if col not in frame.columns:
            frame[col] = None
    frame = frame[keep].copy(deep=True)
    frame["condition_id"] = frame["condition_id"].astype(str)
    frame["direction"] = frame["direction"].astype(str).str.upper()
    frame["role"] = frame["role"].astype(str)
    frame["timeframe"] = frame["timeframe"].astype(str)
    frame["indicator_family"] = frame["indicator_family"].astype(str)
    frame = frame.drop_duplicates(subset=["condition_id", "direction"], keep="first")
    return frame


def _condition_meta(condition_id: str, library: pd.DataFrame) -> dict[str, str]:
    cid = str(condition_id)
    if cid in CONDITION_OVERRIDES:
        payload = dict(CONDITION_OVERRIDES[cid])
        payload["condition_id"] = cid
        payload["source"] = "override"
        return payload

    direction = _infer_direction(cid)

    if not library.empty:
        exact = library[(library["condition_id"] == cid) & (library["direction"] == direction)]
        if exact.empty:
            exact = library[library["condition_id"] == cid]
        if not exact.empty:
            row = exact.iloc[0]
            return {
                "condition_id": cid,
                "direction": str(row.get("direction") or direction or "UNKNOWN").upper(),
                "role": str(row.get("role") or "未标注"),
                "timeframe": str(row.get("timeframe") or _infer_timeframe_from_condition_id(cid)),
                "indicator_family": str(row.get("indicator_family") or "Unknown"),
                "source": "library",
            }

    timeframe = _infer_timeframe_from_condition_id(cid)
    role = DEFAULT_ROLE_BY_TF.get(timeframe, "未标注")
    return {
        "condition_id": cid,
        "direction": direction,
        "role": role,
        "timeframe": timeframe,
        "indicator_family": "Unknown",
        "source": "inferred",
    }


def _load_summary(run_root: Path) -> dict[str, Any]:
    path = run_root / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"missing summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_decision_rows(run_root: Path) -> pd.DataFrame:
    path = run_root / "timelines" / "decision_trace.parquet"
    if not path.exists():
        raise FileNotFoundError(f"missing decision_trace: {path}")
    frame = pd.read_parquet(path).copy(deep=True)
    frame["signal_time"] = pd.to_datetime(frame.get("signal_time"), utc=True, errors="coerce")
    frame["symbol"] = frame.get("symbol", "").astype(str).str.upper()
    frame["action"] = frame.get("action", "").astype(str)
    frame["action_raw"] = frame.get("action_raw", frame["action"]).astype(str)
    frame["score_total"] = pd.to_numeric(frame.get("score_total"), errors="coerce")

    def _side(action_raw: str) -> str:
        if action_raw == "ENTER_LONG":
            return "LONG"
        if action_raw == "ENTER_SHORT":
            return "SHORT"
        return ""

    frame["side"] = frame["action_raw"].map(_side)
    frame["is_enter_row"] = frame["action_raw"].isin(["ENTER_LONG", "ENTER_SHORT"]) | frame["action"].eq("ENTER")

    cond_hits: list[list[str]] = []
    for _, row in frame.iterrows():
        rule_obj = _parse_json_obj(row.get("rule_results_json"))
        hits = rule_obj.get("condition_hits")
        if isinstance(hits, list):
            uniq = sorted({str(item).strip() for item in hits if str(item).strip()})
            cond_hits.append(uniq)
        else:
            cond_hits.append([])
    frame["condition_hits"] = cond_hits
    return frame[["signal_time", "symbol", "action", "action_raw", "side", "is_enter_row", "score_total", "condition_hits"]]


def _load_filled_entries_with_trades(run_root: Path) -> pd.DataFrame:
    action_input_path = run_root / "snapshots" / "action_input.parquet"
    trades_path = run_root / "ledgers" / "trades.parquet"
    if not action_input_path.exists() or not trades_path.exists():
        return pd.DataFrame(columns=["signal_time", "execution_time", "symbol", "action", "side", "net_pnl"])

    actions = pd.read_parquet(action_input_path).copy(deep=True)
    trades = pd.read_parquet(trades_path).copy(deep=True)

    for col in ("signal_time", "execution_time"):
        if col in actions.columns:
            actions[col] = pd.to_datetime(actions[col], utc=True, errors="coerce")
    actions["symbol"] = actions.get("symbol", "").astype(str).str.upper()
    actions["action"] = actions.get("action", "").astype(str)
    actions["status"] = actions.get("status", "").astype(str).str.upper()
    entries = actions[(actions["status"] == "FILLED") & (actions["action"].isin(["ENTER_LONG", "ENTER_SHORT"]))][
        ["signal_time", "execution_time", "symbol", "action"]
    ].copy(deep=True)
    if entries.empty:
        return pd.DataFrame(columns=["signal_time", "execution_time", "symbol", "action", "side", "net_pnl"])
    entries["side"] = np.where(entries["action"] == "ENTER_LONG", "LONG", "SHORT")

    trades["entry_time"] = pd.to_datetime(trades.get("entry_time"), utc=True, errors="coerce")
    trades["symbol"] = trades.get("symbol", "").astype(str).str.upper()
    trades["side"] = trades.get("side", "").astype(str).str.upper()
    trades["net_pnl"] = pd.to_numeric(trades.get("net_pnl"), errors="coerce")

    keep = (
        trades[["symbol", "side", "entry_time", "net_pnl"]]
        .dropna(subset=["entry_time"])
        .sort_values("entry_time")
        .drop_duplicates(subset=["symbol", "side", "entry_time"], keep="first")
    )

    merged = entries.merge(
        keep,
        left_on=["symbol", "side", "execution_time"],
        right_on=["symbol", "side", "entry_time"],
        how="left",
    ).drop(columns=["entry_time"], errors="ignore")
    return merged


def _join_entry_conditions(decision_rows: pd.DataFrame, filled_entries: pd.DataFrame) -> pd.DataFrame:
    if filled_entries.empty:
        return pd.DataFrame(columns=["signal_time", "symbol", "side", "score_total", "condition_hits", "net_pnl"])
    entry_trace = decision_rows[decision_rows["is_enter_row"]].copy(deep=True)
    entry_trace = entry_trace[entry_trace["side"].isin(["LONG", "SHORT"])]
    entry_trace = entry_trace[["signal_time", "symbol", "side", "score_total", "condition_hits"]]
    entry_trace = entry_trace.drop_duplicates(subset=["signal_time", "symbol", "side"], keep="last")

    out = filled_entries.merge(
        entry_trace,
        on=["signal_time", "symbol", "side"],
        how="left",
    )
    out["condition_hits"] = out["condition_hits"].apply(lambda x: x if isinstance(x, list) else [])
    return out


def _auc_from_scores(y_true: pd.Series, scores: pd.Series) -> float:
    labels = pd.to_numeric(y_true, errors="coerce")
    scr = pd.to_numeric(scores, errors="coerce")
    valid = ~(labels.isna() | scr.isna())
    labels = labels[valid].astype(int)
    scr = scr[valid]
    n_pos = int((labels == 1).sum())
    n_neg = int((labels == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = scr.rank(method="average")
    sum_ranks_pos = float(ranks[labels == 1].sum())
    auc = (sum_ranks_pos - (n_pos * (n_pos + 1) / 2.0)) / (n_pos * n_neg)
    return float(auc)


def _score_bins(df: pd.DataFrame, bins: int, scheme: str) -> pd.DataFrame:
    local = df.copy(deep=True)
    if local.empty:
        return pd.DataFrame()
    local = local.dropna(subset=["confidence", "net_pnl"]) 
    if local.empty:
        return pd.DataFrame()
    q = min(bins, int(local["confidence"].nunique()))
    if q < 2:
        return pd.DataFrame()
    local["bin"] = pd.qcut(local["confidence"], q=q, labels=False, duplicates="drop")
    grouped = local.groupby("bin", as_index=False).agg(
        sample_count=("net_pnl", "size"),
        confidence_mean=("confidence", "mean"),
        win_rate=("net_pnl", lambda x: float((pd.to_numeric(x, errors="coerce") > 0).mean())),
        expectancy=("net_pnl", lambda x: float(pd.to_numeric(x, errors="coerce").mean())),
    )
    pf_vals = []
    for _, row in grouped.iterrows():
        subset = local[local["bin"] == row["bin"]]["net_pnl"]
        pf_vals.append(_safe_pf(subset))
    grouped["profit_factor"] = pf_vals
    grouped["scheme"] = scheme
    grouped["bin_index"] = grouped["bin"].astype(int)
    return grouped[["scheme", "bin_index", "sample_count", "confidence_mean", "win_rate", "expectancy", "profit_factor"]]


def _monotonic_violations(values: pd.Series) -> int:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_list()
    if len(clean) < 2:
        return 0
    violations = 0
    for idx in range(1, len(clean)):
        if clean[idx] < clean[idx - 1]:
            violations += 1
    return int(violations)


def _ece_from_rank_probability(df: pd.DataFrame, bins: int = 10) -> float:
    local = df.dropna(subset=["confidence", "net_pnl"]).copy(deep=True)
    if local.empty:
        return float("nan")
    local["label"] = (pd.to_numeric(local["net_pnl"], errors="coerce") > 0).astype(int)
    local["pred_prob"] = local["confidence"].rank(method="average", pct=True)
    q = min(bins, int(local["pred_prob"].nunique()))
    if q < 2:
        return float("nan")
    local["bin"] = pd.qcut(local["pred_prob"], q=q, labels=False, duplicates="drop")
    total = len(local.index)
    ece = 0.0
    for _, grp in local.groupby("bin"):
        w = len(grp.index) / total
        pred = float(grp["pred_prob"].mean())
        obs = float(grp["label"].mean())
        ece += w * abs(pred - obs)
    return float(ece)


def _analyze_single_run(
    run: RunInput,
    *,
    library: pd.DataFrame,
    weak_hit_threshold: float,
    weak_expectancy_eps: float,
    unstable_std_threshold: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame]:
    summary = _load_summary(run.run_root)
    decision_rows = _load_decision_rows(run.run_root)
    filled_entries = _load_filled_entries_with_trades(run.run_root)
    entries = _join_entry_conditions(decision_rows, filled_entries)

    total_rows = int(len(decision_rows.index))
    total_enter_rows = int(decision_rows["is_enter_row"].sum())

    # global condition count from all decision rows
    cond_all = Counter()
    cond_enter = Counter()
    for _, row in decision_rows.iterrows():
        hits = set(row["condition_hits"])
        cond_all.update(hits)
        if bool(row["is_enter_row"]):
            cond_enter.update(hits)

    condition_rows: list[dict[str, Any]] = []
    all_cond_ids = sorted(set(cond_all.keys()).union(cond_enter.keys()))

    for cond_id in all_cond_ids:
        meta = _condition_meta(cond_id, library)
        hit_all = int(cond_all[cond_id])
        hit_enter = int(cond_enter[cond_id])
        hit_rate_all = (hit_all / total_rows) if total_rows > 0 else float("nan")
        hit_rate_enter = (hit_enter / total_enter_rows) if total_enter_rows > 0 else float("nan")
        enter_lift = hit_rate_enter - hit_rate_all if pd.notna(hit_rate_all) and pd.notna(hit_rate_enter) else float("nan")

        eval_entries = entries.copy(deep=True)
        direction = str(meta.get("direction", "UNKNOWN")).upper()
        if direction in {"LONG", "SHORT"}:
            eval_entries = eval_entries[eval_entries["side"] == direction]

        trade_eval = eval_entries.dropna(subset=["net_pnl"]).copy(deep=True)
        if trade_eval.empty:
            exp_hit = exp_miss = win_hit = win_miss = pf_hit = pf_miss = float("nan")
            stdev_monthly = float("nan")
            n_hit = n_miss = 0
        else:
            hit_mask = trade_eval["condition_hits"].apply(lambda arr: cond_id in set(arr))
            hit_vals = trade_eval.loc[hit_mask, "net_pnl"]
            miss_vals = trade_eval.loc[~hit_mask, "net_pnl"]
            exp_hit = _safe_expectancy(hit_vals)
            exp_miss = _safe_expectancy(miss_vals)
            win_hit = _safe_win_rate(hit_vals)
            win_miss = _safe_win_rate(miss_vals)
            pf_hit = _safe_pf(hit_vals)
            pf_miss = _safe_pf(miss_vals)
            n_hit = int(hit_vals.notna().sum())
            n_miss = int(miss_vals.notna().sum())

            monthly_uplifts: list[float] = []
            trade_eval = trade_eval.assign(month=trade_eval["signal_time"].dt.strftime("%Y-%m"))
            for _, grp in trade_eval.groupby("month"):
                grp_hit = grp[grp["condition_hits"].apply(lambda arr: cond_id in set(arr))]["net_pnl"]
                grp_miss = grp[~grp["condition_hits"].apply(lambda arr: cond_id in set(arr))]["net_pnl"]
                if grp_hit.dropna().empty or grp_miss.dropna().empty:
                    continue
                monthly_uplifts.append(_safe_expectancy(grp_hit) - _safe_expectancy(grp_miss))
            stdev_monthly = float(np.std(monthly_uplifts, ddof=1)) if len(monthly_uplifts) >= 2 else float("nan")

        exp_uplift = exp_hit - exp_miss if pd.notna(exp_hit) and pd.notna(exp_miss) else float("nan")
        win_uplift = win_hit - win_miss if pd.notna(win_hit) and pd.notna(win_miss) else float("nan")
        pf_uplift = pf_hit - pf_miss if pd.notna(pf_hit) and pd.notna(pf_miss) else float("nan")

        flag_common_weak = bool((pd.notna(hit_rate_all) and hit_rate_all > weak_hit_threshold) and (pd.notna(exp_uplift) and abs(exp_uplift) < weak_expectancy_eps))
        flag_negative = bool((pd.notna(pf_uplift) and pf_uplift <= 0.0) and (pd.notna(win_uplift) and win_uplift <= 0.0))
        flag_unstable = bool(pd.notna(stdev_monthly) and stdev_monthly >= unstable_std_threshold)

        condition_rows.append(
            {
                "profile_id": run.profile_id,
                "condition_id": cond_id,
                "direction": direction,
                "timeframe": meta.get("timeframe", "unknown"),
                "role": meta.get("role", "未标注"),
                "indicator_family": meta.get("indicator_family", "Unknown"),
                "meta_source": meta.get("source", "inferred"),
                "hit_count_all_rows": hit_all,
                "hit_rate_all_rows": hit_rate_all,
                "hit_count_enter_rows": hit_enter,
                "hit_rate_enter_rows": hit_rate_enter,
                "enter_lift": enter_lift,
                "trade_eval_count_hit": n_hit,
                "trade_eval_count_miss": n_miss,
                "expectancy_hit": exp_hit,
                "expectancy_miss": exp_miss,
                "expectancy_uplift": exp_uplift,
                "win_rate_hit": win_hit,
                "win_rate_miss": win_miss,
                "win_rate_uplift": win_uplift,
                "pf_hit": pf_hit,
                "pf_miss": pf_miss,
                "pf_uplift": pf_uplift,
                "stability_monthly_std": stdev_monthly,
                "flag_common_weak": flag_common_weak,
                "flag_negative_contrib": flag_negative,
                "flag_unstable": flag_unstable,
                "is_prune_candidate": bool(flag_common_weak or flag_negative or flag_unstable),
            }
        )

    condition_df = pd.DataFrame(condition_rows)

    # role-timeframe matrix (profile-level)
    role_tf_df = pd.DataFrame()
    if not condition_df.empty:
        role_tf_df = (
            condition_df.groupby(["profile_id", "timeframe", "role", "direction"], dropna=False)
            .agg(
                condition_count=("condition_id", "count"),
                coverage=("hit_rate_all_rows", "mean"),
                selectivity=("enter_lift", "mean"),
                quality_uplift_expectancy=("expectancy_uplift", "mean"),
                quality_uplift_win_rate=("win_rate_uplift", "mean"),
                quality_uplift_pf=("pf_uplift", "mean"),
            )
            .reset_index()
        )

    # score effectiveness on filled entries/trades
    score_rank_rows: list[dict[str, Any]] = []
    score_bin_rows: list[dict[str, Any]] = []
    score_mono_rows: list[dict[str, Any]] = []

    if not entries.empty:
        entries = entries.dropna(subset=["score_total", "net_pnl"]).copy(deep=True)
        for side in ("LONG", "SHORT"):
            local = entries[entries["side"] == side].copy(deep=True)
            if local.empty:
                continue
            local["confidence"] = local["score_total"] if side == "LONG" else -local["score_total"]
            local["label_win"] = (pd.to_numeric(local["net_pnl"], errors="coerce") > 0).astype(int)

            spearman = float(local["confidence"].corr(local["net_pnl"], method="spearman")) if len(local.index) > 1 else float("nan")
            kendall = float(local["confidence"].corr(local["net_pnl"], method="kendall")) if len(local.index) > 1 else float("nan")
            auc = _auc_from_scores(local["label_win"], local["confidence"])
            ece = _ece_from_rank_probability(local[["confidence", "net_pnl"]], bins=10)

            score_rank_rows.append(
                {
                    "profile_id": run.profile_id,
                    "side": side,
                    "sample_count": int(len(local.index)),
                    "spearman_score_pnl": spearman,
                    "kendall_score_pnl": kendall,
                    "auc_score_win": auc,
                    "calibration_error_ece": ece,
                    "confidence_min": float(local["confidence"].min()),
                    "confidence_p50": float(local["confidence"].quantile(0.5)),
                    "confidence_p80": float(local["confidence"].quantile(0.8)),
                    "confidence_max": float(local["confidence"].max()),
                }
            )

            for bins, scheme in ((10, "decile"), (20, "ventile")):
                bdf = _score_bins(local[["confidence", "net_pnl"]], bins=bins, scheme=scheme)
                if bdf.empty:
                    continue
                bdf = bdf.sort_values("confidence_mean").reset_index(drop=True)
                bdf["profile_id"] = run.profile_id
                bdf["side"] = side
                score_bin_rows.append(bdf)
                score_mono_rows.append(
                    {
                        "profile_id": run.profile_id,
                        "side": side,
                        "scheme": scheme,
                        "bin_count": int(len(bdf.index)),
                        "monotonic_violation_count_win_rate": _monotonic_violations(bdf["win_rate"]),
                        "monotonic_violation_count_expectancy": _monotonic_violations(bdf["expectancy"]),
                        "monotonic_violation_count_pf": _monotonic_violations(bdf["profit_factor"]),
                    }
                )

    score_ranking_df = pd.DataFrame(score_rank_rows)
    score_bins_df = pd.concat(score_bin_rows, ignore_index=True) if score_bin_rows else pd.DataFrame()
    score_mono_df = pd.DataFrame(score_mono_rows)

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
        "trace_rows": total_rows,
        "trace_enter_rows": total_enter_rows,
        "filled_entry_rows": int(len(filled_entries.index)),
        "filled_entry_with_trade_pnl": int(entries.dropna(subset=["net_pnl"]).shape[0]) if not entries.empty else 0,
    }

    prune_df = condition_df[condition_df["is_prune_candidate"]].copy(deep=True)

    return condition_df, role_tf_df, score_ranking_df, score_bins_df, summary_row, prune_df, score_mono_df


def _build_report(
    *,
    out_dir: Path,
    summary_df: pd.DataFrame,
    cond_agg_df: pd.DataFrame,
    prune_df: pd.DataFrame,
    score_rank_df: pd.DataFrame,
    score_mono_df: pd.DataFrame,
) -> str:
    lines: list[str] = []
    lines.append("# Profile Diagnostics V2")
    lines.append("")
    lines.append(f"- generated_at: `{pd.Timestamp.utcnow().isoformat()}`")
    lines.append(f"- output_dir: `{out_dir}`")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    cols = ["profile_id", "trade_count", "net_return", "max_drawdown", "win_rate", "profit_factor", "expectancy"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for _, row in summary_df[cols].iterrows():
        values = [f"{row[c]:.6f}" if isinstance(row[c], float) else str(row[c]) for c in cols]
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")

    lines.append("## Top Common-Weak Conditions")
    lines.append("")
    if cond_agg_df.empty:
        lines.append("- none")
    else:
        top = cond_agg_df.sort_values(["avg_hit_rate_all_rows", "abs_avg_expectancy_uplift"], ascending=[False, True]).head(10)
        cols2 = ["condition_id", "direction", "timeframe", "role", "avg_hit_rate_all_rows", "avg_expectancy_uplift", "profile_count"]
        lines.append("| " + " | ".join(cols2) + " |")
        lines.append("|" + "|".join(["---"] * len(cols2)) + "|")
        for _, row in top.iterrows():
            vals = []
            for c in cols2:
                v = row[c]
                if isinstance(v, float):
                    vals.append(f"{v:.6f}")
                else:
                    vals.append(str(v))
            lines.append("| " + " | ".join(vals) + " |")
    lines.append("")

    lines.append("## Score Ranking")
    lines.append("")
    if score_rank_df.empty:
        lines.append("- no score ranking rows")
    else:
        cols3 = ["profile_id", "side", "sample_count", "spearman_score_pnl", "kendall_score_pnl", "auc_score_win", "calibration_error_ece"]
        lines.append("| " + " | ".join(cols3) + " |")
        lines.append("|" + "|".join(["---"] * len(cols3)) + "|")
        for _, row in score_rank_df[cols3].iterrows():
            vals = []
            for c in cols3:
                v = row[c]
                if isinstance(v, float):
                    vals.append(f"{v:.6f}")
                else:
                    vals.append(str(v))
            lines.append("| " + " | ".join(vals) + " |")
    lines.append("")

    lines.append("## Monotonicity Violations")
    lines.append("")
    if score_mono_df.empty:
        lines.append("- no monotonicity rows")
    else:
        cols4 = [
            "profile_id",
            "side",
            "scheme",
            "monotonic_violation_count_win_rate",
            "monotonic_violation_count_expectancy",
            "monotonic_violation_count_pf",
        ]
        lines.append("| " + " | ".join(cols4) + " |")
        lines.append("|" + "|".join(["---"] * len(cols4)) + "|")
        for _, row in score_mono_df[cols4].iterrows():
            vals = [str(row[c]) for c in cols4]
            lines.append("| " + " | ".join(vals) + " |")
    lines.append("")

    lines.append("## Prune Candidates")
    lines.append("")
    lines.append(f"- candidate_rows: `{int(len(prune_df.index))}`")
    lines.append("")

    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", default=[], help="profile_id=run_root; can be repeated")
    parser.add_argument("--out-dir", default="reports/analysis/profile_diagnostics_v2/latest")
    parser.add_argument("--condition-library", default=str(CONDITION_LIBRARY_PATH))
    parser.add_argument("--weak-hit-threshold", type=float, default=0.95)
    parser.add_argument("--weak-expectancy-eps", type=float, default=0.02)
    parser.add_argument("--unstable-std-threshold", type=float, default=0.20)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.run:
        runs = [_parse_run_item(item) for item in list(args.run)]
    else:
        runs = [RunInput(profile_id=k, run_root=Path(v)) for k, v in DEFAULT_RUNS.items()]

    library = _load_condition_library(Path(args.condition_library))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    cond_frames: list[pd.DataFrame] = []
    role_tf_frames: list[pd.DataFrame] = []
    score_rank_frames: list[pd.DataFrame] = []
    score_bins_frames: list[pd.DataFrame] = []
    prune_frames: list[pd.DataFrame] = []
    score_mono_frames: list[pd.DataFrame] = []
    skipped_runs: list[dict[str, str]] = []

    for run in runs:
        if not run.run_root.exists():
            skipped_runs.append({"profile_id": run.profile_id, "run_root": str(run.run_root), "reason": "run_root_missing"})
            continue
        try:
            cond_df, role_tf_df, score_rank_df, score_bins_df, summary_row, prune_df, score_mono_df = _analyze_single_run(
                run,
                library=library,
                weak_hit_threshold=float(args.weak_hit_threshold),
                weak_expectancy_eps=float(args.weak_expectancy_eps),
                unstable_std_threshold=float(args.unstable_std_threshold),
            )
        except FileNotFoundError as exc:
            skipped_runs.append({"profile_id": run.profile_id, "run_root": str(run.run_root), "reason": str(exc)})
            continue

        summary_rows.append(summary_row)
        if not cond_df.empty:
            cond_frames.append(cond_df)
        if not role_tf_df.empty:
            role_tf_frames.append(role_tf_df)
        if not score_rank_df.empty:
            score_rank_frames.append(score_rank_df)
        if not score_bins_df.empty:
            score_bins_frames.append(score_bins_df)
        if not prune_df.empty:
            prune_frames.append(prune_df)
        if not score_mono_df.empty:
            score_mono_frames.append(score_mono_df)

    summary_df = pd.DataFrame(summary_rows).sort_values("profile_id").reset_index(drop=True) if summary_rows else pd.DataFrame()
    cond_df = pd.concat(cond_frames, ignore_index=True) if cond_frames else pd.DataFrame()
    role_tf_df = pd.concat(role_tf_frames, ignore_index=True) if role_tf_frames else pd.DataFrame()
    score_rank_df = pd.concat(score_rank_frames, ignore_index=True) if score_rank_frames else pd.DataFrame()
    score_bins_df = pd.concat(score_bins_frames, ignore_index=True) if score_bins_frames else pd.DataFrame()
    prune_df = pd.concat(prune_frames, ignore_index=True) if prune_frames else pd.DataFrame()
    score_mono_df = pd.concat(score_mono_frames, ignore_index=True) if score_mono_frames else pd.DataFrame()

    cond_agg_df = pd.DataFrame()
    if not cond_df.empty:
        cond_agg_df = (
            cond_df.groupby(["condition_id", "direction", "timeframe", "role"], dropna=False)
            .agg(
                profile_count=("profile_id", "nunique"),
                avg_hit_rate_all_rows=("hit_rate_all_rows", "mean"),
                avg_hit_rate_enter_rows=("hit_rate_enter_rows", "mean"),
                avg_enter_lift=("enter_lift", "mean"),
                avg_expectancy_uplift=("expectancy_uplift", "mean"),
                avg_win_rate_uplift=("win_rate_uplift", "mean"),
                avg_pf_uplift=("pf_uplift", "mean"),
                abs_avg_expectancy_uplift=("expectancy_uplift", lambda x: float(abs(pd.to_numeric(x, errors="coerce").mean()))),
            )
            .reset_index()
            .sort_values(["profile_count", "avg_hit_rate_all_rows"], ascending=[False, False])
            .reset_index(drop=True)
        )

    paths = {
        "summary_comparison_csv": out_dir / "summary_comparison.csv",
        "condition_effectiveness_by_profile_csv": out_dir / "condition_effectiveness_by_profile.csv",
        "condition_effectiveness_aggregated_csv": out_dir / "condition_effectiveness_aggregated.csv",
        "role_tf_effectiveness_matrix_csv": out_dir / "role_tf_effectiveness_matrix.csv",
        "condition_prune_candidates_csv": out_dir / "condition_prune_candidates.csv",
        "score_ranking_metrics_csv": out_dir / "score_ranking_metrics.csv",
        "score_monotonicity_by_profile_csv": out_dir / "score_monotonicity_by_profile.csv",
        "score_calibration_by_profile_csv": out_dir / "score_calibration_by_profile.csv",
        "report_md": out_dir / "report.md",
    }

    summary_df.to_csv(paths["summary_comparison_csv"], index=False)
    cond_df.to_csv(paths["condition_effectiveness_by_profile_csv"], index=False)
    cond_agg_df.to_csv(paths["condition_effectiveness_aggregated_csv"], index=False)
    role_tf_df.to_csv(paths["role_tf_effectiveness_matrix_csv"], index=False)
    prune_df.to_csv(paths["condition_prune_candidates_csv"], index=False)
    score_rank_df.to_csv(paths["score_ranking_metrics_csv"], index=False)
    score_mono_df.to_csv(paths["score_monotonicity_by_profile_csv"], index=False)
    score_bins_df.to_csv(paths["score_calibration_by_profile_csv"], index=False)

    report = _build_report(
        out_dir=out_dir,
        summary_df=summary_df if not summary_df.empty else pd.DataFrame(columns=["profile_id", "trade_count", "net_return", "max_drawdown", "win_rate", "profit_factor", "expectancy"]),
        cond_agg_df=cond_agg_df,
        prune_df=prune_df,
        score_rank_df=score_rank_df,
        score_mono_df=score_mono_df,
    )
    paths["report_md"].write_text(report, encoding="utf-8")

    payload = {
        "status": "SUCCESS",
        "runs_requested": len(runs),
        "runs_processed": int(len(summary_df.index)),
        "runs_skipped": skipped_runs,
        "outputs": {k: str(v) for k, v in paths.items()},
        "row_counts": {
            "summary_rows": int(len(summary_df.index)),
            "condition_rows": int(len(cond_df.index)),
            "condition_aggregated_rows": int(len(cond_agg_df.index)),
            "role_tf_rows": int(len(role_tf_df.index)),
            "prune_rows": int(len(prune_df.index)),
            "score_ranking_rows": int(len(score_rank_df.index)),
            "score_monotonicity_rows": int(len(score_mono_df.index)),
            "score_calibration_rows": int(len(score_bins_df.index)),
        },
        "params": {
            "weak_hit_threshold": float(args.weak_hit_threshold),
            "weak_expectancy_eps": float(args.weak_expectancy_eps),
            "unstable_std_threshold": float(args.unstable_std_threshold),
            "condition_library": str(args.condition_library),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
