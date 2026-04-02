"""Feature-engine pipeline for indicator_plan driven computation."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import pandas as pd

from xtrader.strategies.feature_engine.errors import xtr018_error
from xtrader.strategies.feature_engine.indicators.base import format_param_value_for_column
from xtrader.strategies.feature_engine.indicators.registry import IndicatorRegistry, build_default_indicator_registry


_REQUIRED_INPUT_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "open", "high", "low", "close", "volume")
_REQUIRED_PLAN_FIELDS: tuple[str, ...] = ("instance_id", "family", "params")
_MULTI_OUTPUT_SUFFIXES: dict[str, tuple[str, ...]] = {
    "macd": ("line", "signal", "hist"),
    "bollinger": ("mid", "up", "low"),
    "kd": ("k", "d", "j"),
    "dmi": ("plus_di", "minus_di", "adx"),
}
_FEATURE_REF_PATTERN = re.compile(r"^f:([0-9]+[smhdw]):([^:]+):([^:]+)$")
_TIMEFRAME_MULTIPLIER: dict[str, str] = {
    "s": "s",
    "m": "min",
    "h": "h",
    "d": "d",
    "w": "W",
}


@dataclass(frozen=True, slots=True)
class PlanItem:
    instance_id: str
    family: str
    params: dict[str, Any]


class FeaturePipeline:
    """Compute indicator features and merge with bars frame."""

    def __init__(self, registry: IndicatorRegistry | None = None) -> None:
        self.registry = registry or build_default_indicator_registry()

    def compute_features(self, *, bars_df: pd.DataFrame, indicator_plan: list[dict[str, Any]]) -> pd.DataFrame:
        self._validate_input_bars(bars_df)
        plan = self._validate_and_normalize_plan(indicator_plan)

        features = pd.DataFrame(index=bars_df.index)
        seen_instance_ids: set[str] = set()
        seen_family_params: set[tuple[str, tuple[tuple[str, Any], ...]]] = set()

        for item in plan:
            if item.instance_id in seen_instance_ids:
                raise xtr018_error("PLAN_DUPLICATE_INSTANCE_ID", item.instance_id)
            seen_instance_ids.add(item.instance_id)

            indicator = self.registry.get(item.family)
            resolved = indicator.resolve_params(item.params)
            family_signature = (
                indicator.name,
                tuple((key, _normalize_signature_value(resolved[key])) for key in sorted(resolved)),
            )
            if family_signature in seen_family_params:
                raise xtr018_error("PLAN_DUPLICATE_FAMILY_PARAMS", f"{indicator.name}.{item.instance_id}")
            seen_family_params.add(family_signature)

            feature_part = indicator.compute(bars_df, resolved)
            if not isinstance(feature_part, pd.DataFrame):
                raise xtr018_error("OUTPUT_COLUMN_CONFLICT", f"{indicator.name} did not return DataFrame")
            if len(feature_part.index) != len(bars_df.index):
                raise xtr018_error("OUTPUT_COLUMN_CONFLICT", f"{indicator.name} row count mismatch")
            if not feature_part.index.equals(bars_df.index):
                raise xtr018_error("OUTPUT_COLUMN_CONFLICT", f"{indicator.name} index mismatch")
            if "timestamp" in feature_part.columns:
                raise xtr018_error("OUTPUT_COLUMN_CONFLICT", f"{indicator.name} produced timestamp column")
            overlaps = sorted(set(feature_part.columns).intersection(features.columns))
            if overlaps:
                raise xtr018_error("OUTPUT_COLUMN_CONFLICT", ",".join(overlaps))
            features = pd.concat([features, feature_part], axis=1)

        return features

    def build_model_df(self, *, bars_df: pd.DataFrame, indicator_plan: list[dict[str, Any]]) -> pd.DataFrame:
        bars_copy = bars_df.copy(deep=True)
        features = self.compute_features(bars_df=bars_copy, indicator_plan=indicator_plan)
        model_df = pd.concat([bars_copy, features], axis=1)
        return model_df

    def build_model_df_by_timeframe(
        self,
        *,
        bars_by_timeframe: dict[str, pd.DataFrame],
        indicator_plan_by_tf: dict[str, list[dict[str, Any]]],
    ) -> dict[str, pd.DataFrame]:
        if not isinstance(bars_by_timeframe, dict):
            raise xtr018_error("PROFILE_INPUT_INVALID", "bars_by_timeframe must be object")
        if not isinstance(indicator_plan_by_tf, dict):
            raise xtr018_error("PROFILE_INPUT_INVALID", "indicator_plan_by_tf must be object")

        output: dict[str, pd.DataFrame] = {}
        for timeframe, plan in indicator_plan_by_tf.items():
            bars = bars_by_timeframe.get(timeframe)
            if not isinstance(bars, pd.DataFrame):
                raise xtr018_error("PROFILE_MISSING_TIMEFRAME_BARS", str(timeframe))
            output[str(timeframe)] = self.build_model_df(
                bars_df=bars.copy(deep=True),
                indicator_plan=list(plan),
            )
        return output

    def build_profile_model_df(
        self,
        *,
        bars_by_timeframe: dict[str, pd.DataFrame],
        required_indicator_plan_by_tf: dict[str, list[dict[str, Any]]],
        required_feature_refs: list[str],
        decision_timeframe: str,
        alignment_policy: dict[str, Any],
    ) -> pd.DataFrame:
        decision_tf = str(decision_timeframe).strip()
        if decision_tf not in required_indicator_plan_by_tf:
            raise xtr018_error("PROFILE_MISSING_TIMEFRAME_PLAN", decision_tf)

        model_by_tf = self.build_model_df_by_timeframe(
            bars_by_timeframe=bars_by_timeframe,
            indicator_plan_by_tf=required_indicator_plan_by_tf,
        )
        if decision_tf not in model_by_tf:
            raise xtr018_error("PROFILE_MISSING_TIMEFRAME_BARS", decision_tf)

        mode = str(alignment_policy.get("mode", "")).strip()
        if mode != "ffill_last_closed":
            raise xtr018_error("PROFILE_ALIGNMENT_MODE_INVALID", mode or "<empty>")
        staleness_cfg = dict(alignment_policy.get("max_staleness_bars_by_tf") or {})

        decision_frame = model_by_tf[decision_tf].copy(deep=True).reset_index(drop=True)
        output = decision_frame[list(_REQUIRED_INPUT_COLUMNS)].copy(deep=True)
        decision_delta = _timeframe_to_timedelta(decision_tf)

        for feature_ref in required_feature_refs:
            source_tf, instance_id, output_key = _parse_feature_ref(feature_ref)
            source_model = model_by_tf.get(source_tf)
            if source_model is None:
                raise xtr018_error("PROFILE_MISSING_TIMEFRAME_BARS", source_tf)
            physical_col = self._resolve_physical_col(
                timeframe=source_tf,
                instance_id=instance_id,
                output_key=output_key,
                indicator_plan_by_tf=required_indicator_plan_by_tf,
            )
            if physical_col not in source_model.columns:
                raise xtr018_error("PROFILE_UNRESOLVED_FEATURE_REF", feature_ref)

            if source_tf == decision_tf:
                output[feature_ref] = source_model[physical_col].to_numpy()
                continue

            source_duration = _timeframe_to_timedelta(source_tf)
            source_view = source_model[["timestamp", physical_col]].copy(deep=True)
            source_view["effective_ts"] = source_view["timestamp"] + source_duration
            source_view = source_view.sort_values("effective_ts").reset_index(drop=True)

            merged = pd.merge_asof(
                left=output[["timestamp"]].sort_values("timestamp"),
                right=source_view[["effective_ts", physical_col]].sort_values("effective_ts"),
                left_on="timestamp",
                right_on="effective_ts",
                direction="backward",
            )
            aligned_series = pd.Series(merged[physical_col].to_numpy(), index=output.index, dtype="float64")
            effective_ts = pd.to_datetime(merged["effective_ts"], utc=True, errors="coerce")
            max_staleness = staleness_cfg.get(source_tf)
            if max_staleness is not None:
                if not isinstance(max_staleness, int) or max_staleness < 1:
                    raise xtr018_error("PROFILE_STALENESS_INVALID", f"{source_tf}:{max_staleness}")
                age = (
                    (output["timestamp"] - effective_ts).dt.total_seconds()
                    / decision_delta.total_seconds()
                )
                aligned_series = aligned_series.mask(effective_ts.isna() | (age > float(max_staleness)))
            output[feature_ref] = aligned_series.to_numpy()

        return output

    def _validate_input_bars(self, bars_df: pd.DataFrame) -> None:
        missing = [column for column in _REQUIRED_INPUT_COLUMNS if column not in bars_df.columns]
        if missing:
            raise xtr018_error("INPUT_MISSING_COLUMN", ",".join(missing))

        ts = bars_df["timestamp"]
        if ts.isna().any():
            raise xtr018_error("INPUT_TIMESTAMP_INVALID", "timestamp has null values")
        if not isinstance(ts.dtype, pd.DatetimeTZDtype):
            raise xtr018_error("INPUT_TIMESTAMP_INVALID", "timestamp must be datetime64tz")
        tz = getattr(ts.dt, "tz", None)
        if tz is None or str(tz) != "UTC":
            raise xtr018_error("INPUT_TIMESTAMP_INVALID", f"timestamp tz must be UTC, got {tz}")
        if ts.duplicated().any():
            raise xtr018_error("INPUT_TIMESTAMP_DUPLICATE", "duplicated timestamp detected")
        if not ts.is_monotonic_increasing:
            raise xtr018_error("INPUT_TIMESTAMP_INVALID", "timestamp must be monotonic increasing")

    def _validate_and_normalize_plan(self, indicator_plan: list[dict[str, Any]]) -> list[PlanItem]:
        if not isinstance(indicator_plan, list):
            raise xtr018_error("PLAN_MISSING_FIELD", "indicator_plan must be list")
        normalized: list[PlanItem] = []
        for idx, raw in enumerate(indicator_plan):
            if not isinstance(raw, dict):
                raise xtr018_error("PLAN_MISSING_FIELD", f"indicator_plan[{idx}] must be object")
            missing = [key for key in _REQUIRED_PLAN_FIELDS if key not in raw]
            if missing:
                raise xtr018_error("PLAN_MISSING_FIELD", f"indicator_plan[{idx}] missing {','.join(missing)}")
            instance_id = str(raw.get("instance_id", "")).strip()
            family = str(raw.get("family", "")).strip().lower()
            params = raw.get("params")
            if not instance_id:
                raise xtr018_error("PLAN_MISSING_FIELD", f"indicator_plan[{idx}].instance_id")
            if not family:
                raise xtr018_error("PLAN_MISSING_FIELD", f"indicator_plan[{idx}].family")
            if not isinstance(params, dict):
                raise xtr018_error("PLAN_MISSING_FIELD", f"indicator_plan[{idx}].params must be object")
            normalized.append(PlanItem(instance_id=instance_id, family=family, params=dict(params)))
        return normalized

    def _resolve_physical_col(
        self,
        *,
        timeframe: str,
        instance_id: str,
        output_key: str,
        indicator_plan_by_tf: dict[str, list[dict[str, Any]]],
    ) -> str:
        plan = indicator_plan_by_tf.get(timeframe)
        if not isinstance(plan, list):
            raise xtr018_error("PROFILE_MISSING_TIMEFRAME_PLAN", timeframe)
        plan_item: dict[str, Any] | None = None
        for item in plan:
            if str(item.get("instance_id", "")).strip() == instance_id:
                plan_item = dict(item)
                break
        if plan_item is None:
            raise xtr018_error("PROFILE_UNRESOLVED_FEATURE_REF", f"{timeframe}:{instance_id}:{output_key}")

        family = str(plan_item["family"]).strip().lower()
        indicator = self.registry.get(family)
        resolved = indicator.resolve_params(dict(plan_item["params"]))
        suffixes = _MULTI_OUTPUT_SUFFIXES.get(family)
        if suffixes is None:
            cols = indicator.build_output_columns(resolved)
            output_map = {"value": cols[0]}
        else:
            cols = indicator.build_output_columns(resolved, suffixes=suffixes)
            output_map = {suffixes[idx]: cols[idx] for idx in range(len(suffixes))}
        if output_key not in output_map:
            raise xtr018_error("PROFILE_UNRESOLVED_FEATURE_REF", f"{timeframe}:{instance_id}:{output_key}")
        return output_map[output_key]


def _normalize_signature_value(value: Any) -> Any:
    if isinstance(value, (int, float, bool)):
        return format_param_value_for_column(value)
    return value


def _parse_feature_ref(value: str) -> tuple[str, str, str]:
    text = str(value).strip()
    matched = _FEATURE_REF_PATTERN.fullmatch(text)
    if matched is None:
        raise xtr018_error("PROFILE_FEATURE_REF_INVALID", text)
    return matched.group(1), matched.group(2), matched.group(3)


def _timeframe_to_timedelta(timeframe: str) -> pd.Timedelta:
    key = str(timeframe).strip().lower()
    matched = re.fullmatch(r"([0-9]+)([smhdw])", key)
    if matched is None:
        raise xtr018_error("PROFILE_TIMEFRAME_INVALID", key)
    qty = int(matched.group(1))
    unit = _TIMEFRAME_MULTIPLIER[matched.group(2)]
    if qty <= 0:
        raise xtr018_error("PROFILE_TIMEFRAME_INVALID", key)
    return pd.to_timedelta(qty, unit=unit)


__all__ = [
    "FeaturePipeline",
    "PlanItem",
    "build_default_indicator_registry",
]
