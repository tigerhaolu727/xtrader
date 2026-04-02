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


def run_score_fn_series(
    *,
    score_fn: str,
    inputs_by_role: dict[str, pd.Series],
    params: dict[str, Any] | None = None,
) -> pd.Series:
    """Evaluate one built-in score_fn and return clipped score series."""

    if score_fn not in SCORE_FN_REGISTRY_V03:
        raise _xtr_sp004_error("UNKNOWN_SCORE_FN", score_fn)

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

                score = run_score_fn_series(
                    score_fn=str(rule["score_fn"]),
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
        score_total = pd.Series(0.0, index=model_df.index, dtype="float64")

        for state_name, normalized_weights in group_weights_by_state.items():
            row_mask = state == state_name
            if not bool(row_mask.any()):
                continue
            total_for_state = pd.Series(0.0, index=model_df.index, dtype="float64")
            for group_id, weight in normalized_weights.items():
                total_for_state = total_for_state + (weight * group_scores[group_id])
            score_total.loc[row_mask] = total_for_state.loc[row_mask]

        score_total = _clip_to_score_range(score_total.fillna(0.0))

        output = model_df[list(required_base)].copy(deep=True)
        output["state"] = state
        output["score_total"] = score_total
        output["rule_scores"] = self._row_map(rule_scores, model_df.index)
        output["group_scores"] = self._row_map(group_scores, model_df.index)
        output["group_weights"] = [
            dict(group_weights_by_state[str(cur_state)])
            for cur_state in output["state"].tolist()
        ]
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


__all__ = ["RegimeScoringEngine", "RegimeScoringResult", "run_score_fn_series"]
