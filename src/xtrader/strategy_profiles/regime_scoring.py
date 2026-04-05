"""Regime scoring runtime for strategy profile v0.3."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

from xtrader.strategy_profiles.score_fn_registry import SCORE_FN_REGISTRY_V03

_EPS = 1e-12
_MOMENTUM_STD_WINDOW_FOR_VOLUME = 96

_SCORE_FN_DEFAULT_PARAMS: dict[str, dict[str, float | int]] = {
    "trend_score": {"atr_scale": 1.5},
    "momentum_score": {"std_window": 96},
    "direction_score": {"adx_floor": 18.0, "adx_span": 12.0},
    "volume_score": {"trend_mix": 0.6, "vol_scale": 0.8, "atr_scale": 1.5},
    "pullback_score": {"dev_scale": 1.2},
}

_TF_POINTS_OP_SYNONYMS: dict[str, str] = {
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "eq": "==",
    "neq": "!=",
}


def _xtr_sp004_error(code: str, detail: str) -> ValueError:
    return ValueError(f"XTRSP004::{code}::{detail}")


def _to_float_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("float64")


def _clip_to_score_range(series: pd.Series) -> pd.Series:
    return series.clip(lower=-1.0, upper=1.0)


def _normalize_group_weights(raw: dict[str, float]) -> dict[str, float]:
    total = float(sum(raw.values()))
    if total <= _EPS:
        return {key: 0.0 for key in raw}
    return {key: float(value) / total for key, value in raw.items()}


def _rolling_std(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).std(ddof=0)


def _series_like(index: pd.Index, value: Any) -> pd.Series:
    return pd.Series([value] * len(index), index=index)


def _to_bool_series(series: pd.Series, *, index: pd.Index) -> pd.Series:
    if not isinstance(series, pd.Series):
        return pd.Series(False, index=index, dtype="bool")
    return series.reindex(index).fillna(False).astype("bool")


def _resolve_tf_operand_series(*, operand: dict[str, Any], inputs: dict[str, pd.Series], index: pd.Index) -> pd.Series:
    if "ref" in operand:
        key = str(operand["ref"])
        if key not in inputs:
            raise _xtr_sp004_error("TF_POINTS_REF_UNKNOWN", key)
        return inputs[key]
    return _series_like(index, operand.get("value"))


def _eval_tf_expr(*, expr: dict[str, Any], inputs: dict[str, pd.Series], index: pd.Index) -> pd.Series:
    op_raw = str(expr.get("op") or "").strip()
    op = _TF_POINTS_OP_SYNONYMS.get(op_raw, op_raw)

    if op == "all_of":
        args = list(expr.get("args") or [])
        out = pd.Series(True, index=index, dtype="bool")
        for item in args:
            out = out & _to_bool_series(_eval_tf_expr(expr=dict(item), inputs=inputs, index=index), index=index)
        return out
    if op == "any_of":
        args = list(expr.get("args") or [])
        out = pd.Series(False, index=index, dtype="bool")
        for item in args:
            out = out | _to_bool_series(_eval_tf_expr(expr=dict(item), inputs=inputs, index=index), index=index)
        return out
    if op == "not":
        arg = dict(expr.get("arg") or {})
        return ~_to_bool_series(_eval_tf_expr(expr=arg, inputs=inputs, index=index), index=index)

    if op == "between":
        value = _resolve_tf_operand_series(operand=dict(expr.get("value") or {}), inputs=inputs, index=index)
        lower = _resolve_tf_operand_series(operand=dict(expr.get("min") or {}), inputs=inputs, index=index)
        upper = _resolve_tf_operand_series(operand=dict(expr.get("max") or {}), inputs=inputs, index=index)
        return (value >= lower) & (value <= upper) & value.notna() & lower.notna() & upper.notna()

    left = _resolve_tf_operand_series(operand=dict(expr.get("left") or {}), inputs=inputs, index=index)
    if op == "in_set":
        raw_set = list(expr.get("set") or [])
        return left.isin(raw_set) & left.notna()

    right = _resolve_tf_operand_series(operand=dict(expr.get("right") or {}), inputs=inputs, index=index)
    valid = left.notna() & right.notna()
    if op == ">":
        return (left > right) & valid
    if op == ">=":
        return (left >= right) & valid
    if op == "<":
        return (left < right) & valid
    if op == "<=":
        return (left <= right) & valid
    if op == "==":
        return (left == right) & valid
    if op == "!=":
        return (left != right) & valid
    if op == "cross_up":
        prev_valid = left.shift(1).notna() & right.shift(1).notna()
        return (left > right) & (left.shift(1) <= right.shift(1)) & valid & prev_valid
    if op == "cross_down":
        prev_valid = left.shift(1).notna() & right.shift(1).notna()
        return (left < right) & (left.shift(1) >= right.shift(1)) & valid & prev_valid
    raise _xtr_sp004_error("TF_POINTS_EXPR_INVALID", op_raw)


def _evaluate_tf_points_rule(
    *,
    rule: dict[str, Any],
    inputs_by_alias: dict[str, pd.Series],
    index: pd.Index,
) -> tuple[pd.Series, dict[str, pd.Series], pd.Series, pd.Series]:
    long_points = pd.Series(0.0, index=index, dtype="float64")
    short_points = pd.Series(0.0, index=index, dtype="float64")
    condition_results: dict[str, pd.Series] = {}

    for item in list(rule.get("long_conditions") or []):
        cond = dict(item)
        cond_id = str(cond["id"])
        hits = _to_bool_series(_eval_tf_expr(expr=dict(cond["expr"]), inputs=inputs_by_alias, index=index), index=index)
        condition_results[cond_id] = hits if cond_id not in condition_results else (condition_results[cond_id] | hits)
        long_points = long_points + (float(cond["points"]) * hits.astype("float64"))

    for item in list(rule.get("short_conditions") or []):
        cond = dict(item)
        cond_id = str(cond["id"])
        hits = _to_bool_series(_eval_tf_expr(expr=dict(cond["expr"]), inputs=inputs_by_alias, index=index), index=index)
        condition_results[cond_id] = hits if cond_id not in condition_results else (condition_results[cond_id] | hits)
        short_points = short_points + (float(cond["points"]) * hits.astype("float64"))

    raw_points = long_points - short_points
    max_abs_points = float(rule.get("max_abs_points") or 1.0)
    if max_abs_points <= _EPS:
        raise _xtr_sp004_error("TF_POINTS_MAX_ABS_INVALID", str(max_abs_points))
    score = _clip_to_score_range(raw_points / max_abs_points)
    return score.astype("float64"), condition_results, long_points.astype("float64"), short_points.astype("float64")


def _extract_macd_state_row_maps(model_df: pd.DataFrame, *, decision_timeframe: str | None = None) -> list[dict[str, Any]]:
    field_map = {
        "state_code": "macd_state_code",
        "near_cross": "macd_near_cross",
        "reject_long": "macd_reject_long",
        "reject_short": "macd_reject_short",
        "gap": "macd_gap",
        "gap_slope": "macd_gap_slope",
        "gap_pct": "macd_gap_pct",
    }
    available = {out: col for out, col in field_map.items() if col in model_df.columns}
    if not available:
        suffix_to_field = {
            "state_code_num": "state_code",
            "near_cross_num": "near_cross",
            "reject_long_flag": "reject_long",
            "reject_short_flag": "reject_short",
            "gap": "gap",
            "gap_slope": "gap_slope",
            "gap_pct": "gap_pct",
        }
        candidates: dict[tuple[str, str], dict[str, str]] = {}
        for column in model_df.columns:
            parts = str(column).split(":")
            if len(parts) != 4 or parts[0] != "f":
                continue
            timeframe, instance_id, suffix = parts[1], parts[2], parts[3]
            field = suffix_to_field.get(suffix)
            if field is None:
                continue
            key = (str(timeframe), str(instance_id))
            candidates.setdefault(key, {})[field] = str(column)

        if candidates:
            preferred_tf = str(decision_timeframe or "").strip().lower()
            best_key: tuple[str, str] | None = None
            best_score = -1
            for key, payload in candidates.items():
                score = len(payload)
                if preferred_tf and str(key[0]).lower() == preferred_tf:
                    score += 100
                if score > best_score:
                    best_score = score
                    best_key = key
            if best_key is not None:
                available = dict(candidates[best_key])

    if not available:
        return [{} for _ in range(len(model_df.index))]

    rows: list[dict[str, Any]] = []
    for _, row in model_df.iterrows():
        meta: dict[str, Any] = {}
        if "gap" in available:
            meta["gap"] = row.get(available["gap"])
        if "gap_slope" in available:
            meta["gap_slope"] = row.get(available["gap_slope"])
        if "gap_pct" in available:
            meta["gap_pct"] = row.get(available["gap_pct"])
        item: dict[str, Any] = {}
        for key in ("state_code", "near_cross", "reject_long", "reject_short"):
            if key in available:
                item[key] = row.get(available[key])
        if meta:
            item["meta"] = meta
        rows.append(item)
    return rows


def run_score_fn_series(
    *,
    score_fn: str,
    inputs_by_role: dict[str, pd.Series],
    params: dict[str, Any] | None = None,
) -> pd.Series:
    """Evaluate one built-in score_fn and return clipped score series."""

    if score_fn not in SCORE_FN_REGISTRY_V03:
        raise _xtr_sp004_error("UNKNOWN_SCORE_FN", score_fn)

    if score_fn not in _SCORE_FN_DEFAULT_PARAMS:
        raise _xtr_sp004_error("UNSUPPORTED_SCORE_FN_RUNTIME", score_fn)
    defaults = dict(_SCORE_FN_DEFAULT_PARAMS[score_fn])
    resolved_params = defaults | dict(params or {})

    if score_fn == "trend_score":
        ema_fast = _to_float_series(inputs_by_role["ema_fast"])
        ema_slow = _to_float_series(inputs_by_role["ema_slow"])
        atr_main = _to_float_series(inputs_by_role["atr_main"])
        atr_scale = float(resolved_params["atr_scale"])
        denom = atr_scale * atr_main
        ratio = (ema_fast - ema_slow) / denom
        ratio = ratio.mask(denom.abs() <= _EPS)
        score = np.tanh(ratio)
        return _clip_to_score_range(pd.Series(score, index=ema_fast.index, dtype="float64"))

    if score_fn == "momentum_score":
        macd_hist = _to_float_series(inputs_by_role["macd_hist"])
        std_window = int(resolved_params["std_window"])
        denom = _rolling_std(macd_hist, std_window)
        ratio = macd_hist / denom
        ratio = ratio.mask(denom.abs() <= _EPS)
        score = np.tanh(ratio)
        return _clip_to_score_range(pd.Series(score, index=macd_hist.index, dtype="float64"))

    if score_fn == "direction_score":
        plus_di = _to_float_series(inputs_by_role["plus_di"])
        minus_di = _to_float_series(inputs_by_role["minus_di"])
        adx = _to_float_series(inputs_by_role["adx"])
        adx_floor = float(resolved_params["adx_floor"])
        adx_span = float(resolved_params["adx_span"])
        dm_spread = (plus_di - minus_di) / 100.0
        adx_strength = ((adx - adx_floor) / adx_span).clip(lower=0.0, upper=1.0)
        score = dm_spread * adx_strength
        return _clip_to_score_range(pd.Series(score, index=plus_di.index, dtype="float64"))

    if score_fn == "volume_score":
        volume_variation = _to_float_series(inputs_by_role["volume_variation"])
        ema_fast = _to_float_series(inputs_by_role["ema_fast"])
        ema_slow = _to_float_series(inputs_by_role["ema_slow"])
        atr_main = _to_float_series(inputs_by_role["atr_main"])
        macd_hist = _to_float_series(inputs_by_role["macd_hist"])
        trend_mix = float(resolved_params["trend_mix"])
        vol_scale = float(resolved_params["vol_scale"])
        atr_scale = float(resolved_params["atr_scale"])

        denom_trend = atr_scale * atr_main
        trend_raw = (ema_fast - ema_slow) / denom_trend
        trend_raw = trend_raw.mask(denom_trend.abs() <= _EPS)
        trend_proxy = pd.Series(np.tanh(trend_raw), index=volume_variation.index, dtype="float64")

        mom_std = _rolling_std(macd_hist, _MOMENTUM_STD_WINDOW_FOR_VOLUME)
        momentum_raw = macd_hist / mom_std
        momentum_raw = momentum_raw.mask(mom_std.abs() <= _EPS)
        momentum_proxy = pd.Series(np.tanh(momentum_raw), index=volume_variation.index, dtype="float64")

        sign_basis = (trend_mix * trend_proxy) + ((1.0 - trend_mix) * momentum_proxy)
        dir_sign = pd.Series(np.sign(sign_basis), index=volume_variation.index, dtype="float64")

        if abs(vol_scale) <= _EPS:
            vol_amp_raw = pd.Series(np.nan, index=volume_variation.index, dtype="float64")
        else:
            vol_amp_raw = volume_variation / vol_scale
        vol_amp = pd.Series(np.tanh(vol_amp_raw), index=volume_variation.index, dtype="float64")
        score = vol_amp * dir_sign
        return _clip_to_score_range(pd.Series(score, index=volume_variation.index, dtype="float64"))

    if score_fn == "pullback_score":
        close = _to_float_series(inputs_by_role["close"])
        ema_fast = _to_float_series(inputs_by_role["ema_fast"])
        ema_slow = _to_float_series(inputs_by_role["ema_slow"])
        atr_main = _to_float_series(inputs_by_role["atr_main"])
        dev_scale = float(resolved_params["dev_scale"])

        dev = (close - ema_fast) / atr_main
        dev = dev.mask(atr_main.abs() <= _EPS)
        trend_proxy = pd.Series(np.sign(ema_fast - ema_slow), index=close.index, dtype="float64")
        pb_long = ((-dev) / dev_scale).clip(lower=0.0, upper=1.0)
        pb_short = (dev / dev_scale).clip(lower=0.0, upper=1.0)
        score = (pb_long * (trend_proxy > 0).astype("float64")) - (pb_short * (trend_proxy < 0).astype("float64"))
        return _clip_to_score_range(pd.Series(score, index=close.index, dtype="float64"))

    raise _xtr_sp004_error("UNKNOWN_SCORE_FN", score_fn)


def _evaluate_condition(values: pd.Series, cond: dict[str, Any]) -> pd.Series:
    op = str(cond["op"])
    if op == "between":
        lower = float(cond["min"])
        upper = float(cond["max"])
        return (values >= lower) & (values <= upper)

    target = float(cond["value"])
    if op == ">":
        return values > target
    if op == ">=":
        return values >= target
    if op == "<":
        return values < target
    if op == "<=":
        return values <= target
    if op == "==":
        return values == target
    if op == "!=":
        return values != target
    raise _xtr_sp004_error("CLASSIFIER_OP_INVALID", op)


@dataclass(frozen=True, slots=True)
class RegimeScoringResult:
    frame: pd.DataFrame


class RegimeScoringEngine:
    """Compute Rule -> Group -> Regime -> ScoreSynthesizer chain."""

    def run(
        self,
        *,
        resolved_profile: dict[str, Any],
        resolved_input_bindings: dict[str, dict[str, str]],
        model_df: pd.DataFrame,
    ) -> RegimeScoringResult:
        required_base = ("timestamp", "symbol")
        missing_base = [column for column in required_base if column not in model_df.columns]
        if missing_base:
            raise _xtr_sp004_error("MISSING_BASE_COLUMN", ",".join(missing_base))

        regime_spec = dict(resolved_profile["regime_spec"])
        groups = [dict(item) for item in regime_spec["groups"] if bool(item.get("enabled", True))]
        if not groups:
            raise _xtr_sp004_error("NO_ENABLED_GROUP", "regime_spec.groups")

        rule_scores: dict[str, pd.Series] = {}
        rule_condition_results_by_rule: dict[str, dict[str, pd.Series]] = {}
        rule_long_points: dict[str, pd.Series] = {}
        rule_short_points: dict[str, pd.Series] = {}
        for group in groups:
            group_id = str(group["group_id"])
            weights = dict(group["rule_weights"])
            for rule in group["rules"]:
                if not bool(rule.get("enabled", True)):
                    continue
                rule_id = str(rule["rule_id"])
                if rule_id not in weights:
                    raise _xtr_sp004_error("MISSING_RULE_WEIGHT", f"{group_id}:{rule_id}")
                binding = resolved_input_bindings.get(rule_id)
                if binding is None:
                    raise _xtr_sp004_error("MISSING_RULE_BINDING", rule_id)
                inputs_by_role: dict[str, pd.Series] = {}
                for role, feature_ref in binding.items():
                    if feature_ref not in model_df.columns:
                        raise _xtr_sp004_error("MISSING_FEATURE_REF", f"{rule_id}:{feature_ref}")
                    inputs_by_role[str(role)] = model_df[str(feature_ref)]

                score_fn = str(rule["score_fn"])
                if score_fn == "tf_points_score_v1":
                    score, cond_results, long_pts, short_pts = _evaluate_tf_points_rule(
                        rule=dict(rule),
                        inputs_by_alias=inputs_by_role,
                        index=model_df.index,
                    )
                    rule_condition_results_by_rule[rule_id] = cond_results
                    rule_long_points[rule_id] = long_pts
                    rule_short_points[rule_id] = short_pts
                else:
                    score = run_score_fn_series(
                        score_fn=score_fn,
                        inputs_by_role=inputs_by_role,
                        params=dict(rule.get("params") or {}),
                    )
                nan_policy = str(rule.get("nan_policy", "neutral_zero"))
                if nan_policy != "neutral_zero":
                    raise _xtr_sp004_error("UNSUPPORTED_NAN_POLICY", nan_policy)
                score = score.mask(~np.isfinite(score), np.nan).fillna(0.0).astype("float64")
                rule_scores[rule_id] = _clip_to_score_range(score)

        group_scores: dict[str, pd.Series] = {}
        for group in groups:
            group_id = str(group["group_id"])
            weights = dict(group["rule_weights"])
            group_series = pd.Series(0.0, index=model_df.index, dtype="float64")
            has_enabled_rule = False
            for rule in group["rules"]:
                if not bool(rule.get("enabled", True)):
                    continue
                has_enabled_rule = True
                rule_id = str(rule["rule_id"])
                group_series = group_series + (float(weights[rule_id]) * rule_scores[rule_id])
            if not has_enabled_rule:
                raise _xtr_sp004_error("GROUP_NO_ENABLED_RULE", group_id)
            group_scores[group_id] = _clip_to_score_range(group_series)

        state = self._evaluate_classifier(regime_spec=regime_spec, model_df=model_df)
        group_weights_by_state = self._build_group_weights_by_state(regime_spec=regime_spec, group_ids=tuple(group_scores))
        score_base = pd.Series(0.0, index=model_df.index, dtype="float64")

        for state_name, normalized_weights in group_weights_by_state.items():
            row_mask = state == state_name
            if not bool(row_mask.any()):
                continue
            total_for_state = pd.Series(0.0, index=model_df.index, dtype="float64")
            for group_id, weight in normalized_weights.items():
                total_for_state = total_for_state + (weight * group_scores[group_id])
            score_base.loc[row_mask] = total_for_state.loc[row_mask]

        score_base = _clip_to_score_range(score_base.fillna(0.0))
        score_total = score_base.copy(deep=True)
        score_adjustment = pd.Series(0.0, index=model_df.index, dtype="float64")
        state_adjustment_detail = pd.Series([{} for _ in range(len(model_df.index))], index=model_df.index, dtype="object")
        adjustments = dict(regime_spec.get("state_score_adjustments") or {})
        for state_name, adj in adjustments.items():
            row_mask = state == str(state_name)
            if not bool(row_mask.any()):
                continue
            fn = str(dict(adj).get("fn") or "")
            params = dict(dict(adj).get("params") or {})
            if fn != "coherence_adjust_v1":
                raise _xtr_sp004_error("STATE_ADJUSTMENT_FN_UNSUPPORTED", fn)
            adjusted, detail = self._apply_coherence_adjust_v1(
                score_base=score_base,
                group_scores=group_scores,
                normalized_weights=group_weights_by_state.get(str(state_name), {}),
                params=params,
                index=model_df.index,
            )
            score_total.loc[row_mask] = adjusted.loc[row_mask]
            score_adjustment.loc[row_mask] = (adjusted - score_base).loc[row_mask]
            state_adjustment_detail.loc[row_mask] = detail.loc[row_mask]

        score_total = _clip_to_score_range(score_total.fillna(0.0))

        merged_condition_results: dict[str, pd.Series] = {}
        for cond_map in rule_condition_results_by_rule.values():
            for cond_id, series in cond_map.items():
                if cond_id in merged_condition_results:
                    merged_condition_results[cond_id] = merged_condition_results[cond_id] | _to_bool_series(
                        series, index=model_df.index
                    )
                else:
                    merged_condition_results[cond_id] = _to_bool_series(series, index=model_df.index)

        output = model_df[list(required_base)].copy(deep=True)
        output["state"] = state
        output["score_base"] = score_base
        output["score_adjustment"] = score_adjustment
        output["score_total"] = score_total
        output["rule_scores"] = self._row_map(rule_scores, model_df.index)
        output["rule_traces"] = self._build_rule_traces(
            model_index=model_df.index,
            rule_scores=rule_scores,
            rule_condition_results_by_rule=rule_condition_results_by_rule,
            rule_long_points=rule_long_points,
            rule_short_points=rule_short_points,
        )
        output["condition_results"] = self._row_map_bool(merged_condition_results, model_df.index)
        output["condition_hits"] = self._row_hits(merged_condition_results, model_df.index)
        output["group_scores"] = self._row_map(group_scores, model_df.index)
        output["group_weights"] = [
            dict(group_weights_by_state[str(cur_state)])
            for cur_state in output["state"].tolist()
        ]
        output["state_adjustment_detail"] = [
            self._sanitize_json_dict(item)
            for item in state_adjustment_detail.tolist()
        ]
        output["macd_state"] = _extract_macd_state_row_maps(
            model_df,
            decision_timeframe=str(regime_spec.get("decision_timeframe") or ""),
        )
        return RegimeScoringResult(frame=output)

    def _evaluate_classifier(self, *, regime_spec: dict[str, Any], model_df: pd.DataFrame) -> pd.Series:
        classifier = dict(regime_spec["classifier"])
        rules = sorted(
            [dict(item) for item in classifier["rules"] if bool(item.get("enabled", True))],
            key=lambda item: int(item["priority"]),
        )
        default_state = str(classifier["default_state"])
        state = pd.Series([default_state] * len(model_df.index), index=model_df.index, dtype="object")
        matched = pd.Series(False, index=model_df.index, dtype="bool")

        for rule in rules:
            cond_mask = pd.Series(True, index=model_df.index, dtype="bool")
            for cond in rule["conditions"]:
                ref = str(cond["ref"])
                if ref not in model_df.columns:
                    raise _xtr_sp004_error("MISSING_CLASSIFIER_REF", ref)
                values = _to_float_series(model_df[ref])
                this_cond = _evaluate_condition(values, dict(cond))
                this_cond = this_cond & values.notna()
                cond_mask = cond_mask & this_cond
            hit = (~matched) & cond_mask
            if bool(hit.any()):
                state.loc[hit] = str(rule["target_state"])
                matched = matched | hit
        return state

    def _build_group_weights_by_state(
        self,
        *,
        regime_spec: dict[str, Any],
        group_ids: tuple[str, ...],
    ) -> dict[str, dict[str, float]]:
        states = [str(item) for item in regime_spec["states"]]
        state_group_weights = dict(regime_spec["state_group_weights"])
        output: dict[str, dict[str, float]] = {}
        for state in states:
            raw_payload = dict(state_group_weights.get(state) or {})
            raw_map: dict[str, float] = {}
            for group_id in group_ids:
                raw_map[group_id] = float(raw_payload.get(group_id, 0.0))
                if raw_map[group_id] < 0.0:
                    raise _xtr_sp004_error("NEGATIVE_GROUP_WEIGHT", f"{state}:{group_id}")
            output[state] = _normalize_group_weights(raw_map)
        return output

    def _apply_coherence_adjust_v1(
        self,
        *,
        score_base: pd.Series,
        group_scores: dict[str, pd.Series],
        normalized_weights: dict[str, float],
        params: dict[str, Any],
        index: pd.Index,
    ) -> tuple[pd.Series, pd.Series]:
        gain = float(params.get("gain", 0.0))
        weighted_sum = pd.Series(0.0, index=index, dtype="float64")
        weighted_abs_sum = pd.Series(0.0, index=index, dtype="float64")
        for group_id, weight in normalized_weights.items():
            cur = group_scores.get(group_id)
            if cur is None:
                continue
            weighted_sum = weighted_sum + (float(weight) * cur)
            weighted_abs_sum = weighted_abs_sum + (float(weight) * cur.abs())
        coherence = weighted_sum.abs() / (weighted_abs_sum + _EPS)
        adjusted = score_base * (1.0 + (gain * ((2.0 * coherence) - 1.0)))

        high_tf_conflict = pd.Series(False, index=index, dtype="bool")
        high_tf_groups = [str(item) for item in list(params.get("high_tf_groups") or [])]
        selected = [group_scores[g] for g in high_tf_groups if g in group_scores]
        if len(selected) >= 2:
            pos = pd.Series(False, index=index, dtype="bool")
            neg = pd.Series(False, index=index, dtype="bool")
            for series in selected:
                pos = pos | (series > _EPS)
                neg = neg | (series < -_EPS)
            high_tf_conflict = pos & neg

        conflict_cap_raw = params.get("high_tf_conflict_cap")
        if conflict_cap_raw is not None:
            conflict_cap = abs(float(conflict_cap_raw))
            if conflict_cap > _EPS:
                adjusted.loc[high_tf_conflict] = adjusted.loc[high_tf_conflict].clip(lower=-conflict_cap, upper=conflict_cap)

        final = _clip_to_score_range(adjusted)
        detail_rows: list[dict[str, Any]] = []
        for idx in index:
            detail_rows.append(
                {
                    "fn": "coherence_adjust_v1",
                    "params": dict(params),
                    "gain": gain,
                    "coherence": float(coherence.loc[idx]),
                    "high_tf_conflict": bool(high_tf_conflict.loc[idx]),
                }
            )
        detail = pd.Series(detail_rows, index=index, dtype="object")
        return final.astype("float64"), detail

    def _build_rule_traces(
        self,
        *,
        model_index: pd.Index,
        rule_scores: dict[str, pd.Series],
        rule_condition_results_by_rule: dict[str, dict[str, pd.Series]],
        rule_long_points: dict[str, pd.Series],
        rule_short_points: dict[str, pd.Series],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        keys = tuple(rule_scores.keys())
        for idx in model_index:
            row_item: dict[str, Any] = {}
            for rule_id in keys:
                score = float(rule_scores[rule_id].loc[idx])
                if not math.isfinite(score):
                    score = 0.0
                cond_map = rule_condition_results_by_rule.get(rule_id) or {}
                cond_results: dict[str, bool] = {}
                hits: list[str] = []
                for cond_id, cond_series in cond_map.items():
                    hit = bool(cond_series.loc[idx])
                    cond_results[str(cond_id)] = hit
                    if hit:
                        hits.append(str(cond_id))
                item: dict[str, Any] = {"score": score}
                if cond_map:
                    long_pts = float(rule_long_points.get(rule_id, pd.Series(0.0, index=model_index)).loc[idx])
                    short_pts = float(rule_short_points.get(rule_id, pd.Series(0.0, index=model_index)).loc[idx])
                    if not math.isfinite(long_pts):
                        long_pts = 0.0
                    if not math.isfinite(short_pts):
                        short_pts = 0.0
                    item.update(
                        {
                            "long_points": long_pts,
                            "short_points": short_pts,
                            "raw_points": long_pts - short_pts,
                            "condition_hits": {"hits": hits, "results": cond_results},
                        }
                    )
                row_item[rule_id] = item
            rows.append(row_item)
        return rows

    def _row_map(self, payload: dict[str, pd.Series], index: pd.Index) -> list[dict[str, float]]:
        rows: list[dict[str, float]] = []
        keys = tuple(payload.keys())
        if not keys:
            return [{} for _ in range(len(index))]
        for idx in index:
            item: dict[str, float] = {}
            for key in keys:
                value = float(payload[key].loc[idx])
                if not math.isfinite(value):
                    value = 0.0
                item[key] = value
            rows.append(item)
        return rows

    def _row_map_bool(self, payload: dict[str, pd.Series], index: pd.Index) -> list[dict[str, bool]]:
        rows: list[dict[str, bool]] = []
        keys = tuple(payload.keys())
        if not keys:
            return [{} for _ in range(len(index))]
        for idx in index:
            item: dict[str, bool] = {}
            for key in keys:
                item[key] = bool(payload[key].loc[idx])
            rows.append(item)
        return rows

    def _row_hits(self, payload: dict[str, pd.Series], index: pd.Index) -> list[list[str]]:
        keys = tuple(payload.keys())
        if not keys:
            return [[] for _ in range(len(index))]
        rows: list[list[str]] = []
        for idx in index:
            hit_keys: list[str] = []
            for key in keys:
                if bool(payload[key].loc[idx]):
                    hit_keys.append(str(key))
            rows.append(hit_keys)
        return rows

    def _sanitize_json_dict(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, Any] = {}
        for key, raw in value.items():
            if isinstance(raw, dict):
                out[str(key)] = self._sanitize_json_dict(raw)
                continue
            if isinstance(raw, bool):
                out[str(key)] = bool(raw)
                continue
            if isinstance(raw, (int, float)):
                val = float(raw)
                out[str(key)] = 0.0 if not math.isfinite(val) else val
                continue
            if raw is None:
                out[str(key)] = None
                continue
            out[str(key)] = raw
        return out


__all__ = ["RegimeScoringEngine", "RegimeScoringResult", "run_score_fn_series"]
