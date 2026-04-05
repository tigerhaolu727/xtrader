"""Profile-driven action strategy runtime entry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from xtrader.strategies.base import (
    ActionStrategyResult,
    BaseActionStrategy,
    DEFAULT_ACTION_OUTPUT_SCHEMA,
    StrategyContext,
    StrategySpec,
)
from xtrader.strategies.feature_engine.pipeline import FeaturePipeline
from xtrader.strategy_profiles import (
    RegimeScoringEngine,
    RiskEngine,
    SignalEngine,
    StrategyProfilePrecompileEngine,
)

_BASE_MODEL_COLUMNS: set[str] = {"timestamp", "symbol", "open", "high", "low", "close", "volume", "funding_rate"}


def _default_profile_path() -> Path:
    return Path(__file__).resolve().parents[4] / "configs/strategy-profiles/five_min_regime_momentum/v0.3.json"


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_compatible(raw) for key, raw in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            scalar = value.item()
            if scalar is not value:
                return _json_compatible(scalar)
        except Exception:  # pragma: no cover - defensive
            pass
    try:
        if pd.isna(value):
            return None
    except Exception:  # pragma: no cover - defensive
        pass
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, int):
        return int(value)
    return value


class ProfileActionStrategy(BaseActionStrategy):
    """End-to-end profile strategy: feature -> score -> signal -> risk -> action."""

    def __init__(self, *, profile_config: dict[str, Any] | str | Path | None = None) -> None:
        config = profile_config if profile_config is not None else _default_profile_path()
        precompile = StrategyProfilePrecompileEngine().compile(config)
        if precompile.status != "SUCCESS":
            raise ValueError(
                "XTRSP007::PROFILE_PRECOMPILE_FAILED::"
                f"{precompile.error_code}::{precompile.error_path}::{precompile.error_message}"
            )

        self._resolved_profile = dict(precompile.resolved_profile)
        self._required_feature_refs = list(precompile.required_feature_refs)
        self._required_indicator_plan_by_tf = dict(precompile.required_indicator_plan_by_tf)
        self._resolved_input_bindings = dict(precompile.resolved_input_bindings)
        self._feature_pipeline = FeaturePipeline()
        self._scoring_engine = RegimeScoringEngine()
        self._signal_engine = SignalEngine()
        self._risk_engine = RiskEngine()

        self.strategy_id = str(self._resolved_profile["strategy_id"])
        self.version = str(self._resolved_profile["version"])
        self._required_timeframes = tuple(sorted(str(tf) for tf in self._required_indicator_plan_by_tf.keys()))
        if not self._required_timeframes:
            raise ValueError("XTRSP007::PROFILE_RUNTIME_INVALID::no required timeframes")

    def spec(self) -> StrategySpec:
        return StrategySpec(
            strategy_id=self.strategy_id,
            version=self.version,
            required_inputs=self._required_timeframes,
            output_schema=DEFAULT_ACTION_OUTPUT_SCHEMA,
            params_schema={},
        )

    def generate_actions(self, context: StrategyContext) -> ActionStrategyResult:
        bars_by_timeframe: dict[str, pd.DataFrame] = {}
        for timeframe in self._required_timeframes:
            bars = context.require_input(timeframe).copy(deep=True)
            if context.universe:
                bars = bars[bars["symbol"].astype(str).isin(set(context.universe))].copy(deep=True)
            bars_by_timeframe[timeframe] = bars.reset_index(drop=True)

        regime_spec = dict(self._resolved_profile["regime_spec"])
        model_df = self._feature_pipeline.build_profile_model_df(
            bars_by_timeframe=bars_by_timeframe,
            required_indicator_plan_by_tf=self._required_indicator_plan_by_tf,
            required_feature_refs=self._required_feature_refs,
            decision_timeframe=str(regime_spec["decision_timeframe"]),
            alignment_policy=dict(regime_spec["alignment_policy"]),
            include_decision_tf_features=True,
        )
        scoring_df = self._scoring_engine.run(
            resolved_profile=self._resolved_profile,
            resolved_input_bindings=self._resolved_input_bindings,
            model_df=model_df,
        ).frame
        signal_df = self._signal_engine.run(
            resolved_profile=self._resolved_profile,
            scoring_df=scoring_df,
        ).frame
        account_context = context.meta.get("account_context", {}) if isinstance(context.meta, dict) else {}
        if account_context is None:
            account_context = {}
        if not isinstance(account_context, dict):
            raise ValueError("XTRSP007::ACCOUNT_CONTEXT_INVALID::meta.account_context must be object")

        risk_df = self._risk_engine.run(
            resolved_profile=self._resolved_profile,
            signal_df=signal_df,
            market_df=model_df,
            account_context=account_context,
        ).frame
        decision_trace = self._build_decision_trace_frame(
            model_df=model_df,
            scoring_df=scoring_df,
            signal_df=signal_df,
            risk_df=risk_df,
        )
        actions = risk_df[list(DEFAULT_ACTION_OUTPUT_SCHEMA)].copy(deep=True).reset_index(drop=True)
        actions = actions.sort_values(["timestamp", "symbol"]).reset_index(drop=True)

        diagnostics_view = risk_df[["timestamp", "symbol", "state", "score_total", "action", "reason"]].copy(deep=True)
        diagnostics = {
            "input_rows": int(len(model_df.index)),
            "output_rows": int(len(actions.index)),
            "decision_timeframe": str(regime_spec["decision_timeframe"]),
            "required_timeframes": list(self._required_timeframes),
            "state_distribution": {
                str(key): int(value)
                for key, value in scoring_df["state"].value_counts(dropna=False).to_dict().items()
            },
            "action_distribution": {
                str(key): int(value)
                for key, value in actions["action"].value_counts(dropna=False).to_dict().items()
            },
            "diagnostics_columns": ["state", "score_total", "action", "reason"],
            "preview": diagnostics_view.head(20).to_dict(orient="records"),
        }
        result = ActionStrategyResult(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            actions=actions,
            diagnostics=diagnostics,
            decision_trace=decision_trace,
        )
        result.validate_schema(self.spec().output_schema)
        return result

    def _build_decision_trace_frame(
        self,
        *,
        model_df: pd.DataFrame,
        scoring_df: pd.DataFrame,
        signal_df: pd.DataFrame,
        risk_df: pd.DataFrame,
    ) -> pd.DataFrame:
        trace_columns = [
            "signal_time",
            "symbol",
            "action_raw",
            "reason",
            "state",
            "score_total",
            "feature_values",
            "required_feature_refs",
            "required_feature_values",
            "rule_results",
            "group_scores",
            "group_weights",
            "signal_decision",
            "risk_decision",
            "action_result",
        ]
        if risk_df.empty:
            return pd.DataFrame(columns=trace_columns)

        scoring_columns = ["timestamp", "symbol", "rule_scores", "group_scores", "group_weights"]
        optional_scoring = [
            "rule_traces",
            "condition_results",
            "condition_hits",
            "score_base",
            "score_adjustment",
            "state_adjustment_detail",
            "macd_state",
        ]
        for column in optional_scoring:
            if column in scoring_df.columns:
                scoring_columns.append(column)
        scoring_view = scoring_df[scoring_columns].copy(deep=True).reset_index(drop=True)
        signal_view = (
            signal_df[
                [
                    "timestamp",
                    "symbol",
                    "action",
                    "reason_code",
                    "matched_rule_id",
                    *[column for column in ("selected_gate_id", "gate_results") if column in signal_df.columns],
                ]
            ]
            .copy(deep=True)
            .rename(
                columns={
                    "action": "signal_action_raw",
                    "reason_code": "signal_reason_code",
                    "matched_rule_id": "signal_matched_rule_id",
                    "selected_gate_id": "signal_selected_gate_id",
                    "gate_results": "signal_gate_results",
                }
            )
        )

        merged = risk_df.copy(deep=True)
        merged = merged.merge(scoring_view, on=["timestamp", "symbol"], how="left")
        merged = merged.merge(signal_view, on=["timestamp", "symbol"], how="left")

        required_feature_cols = [column for column in self._required_feature_refs if column in model_df.columns]
        full_feature_cols = [
            column
            for column in model_df.columns
            if (
                column not in _BASE_MODEL_COLUMNS
                and column not in required_feature_cols
                and not str(column).startswith("f:")
            )
        ]
        feature_view = model_df[["timestamp", "symbol", *required_feature_cols, *full_feature_cols]].copy(deep=True)
        merged = merged.merge(feature_view, on=["timestamp", "symbol"], how="left")

        rows: list[dict[str, Any]] = []
        for row in merged.to_dict(orient="records"):
            required_refs = list(self._required_feature_refs)
            required_values = {ref: _json_compatible(row.get(ref)) for ref in required_refs}
            feature_values = {column: _json_compatible(row.get(column)) for column in full_feature_cols}
            for ref in required_refs:
                feature_values[ref] = required_values.get(ref)

            signal_decision = {
                "action_raw": _json_compatible(row.get("signal_action_raw")),
                "reason_code": _json_compatible(row.get("signal_reason_code")),
                "matched_rule_id": _json_compatible(row.get("signal_matched_rule_id")),
                "selected_gate_id": _json_compatible(row.get("signal_selected_gate_id")),
                "gate_results": _json_compatible(row.get("signal_gate_results")),
            }
            risk_decision = {
                "action_raw": _json_compatible(row.get("action")),
                "reason_code": _json_compatible(row.get("reason_code")),
                "size": _json_compatible(row.get("size")),
                "stop_loss": _json_compatible(row.get("stop_loss")),
                "take_profit": _json_compatible(row.get("take_profit")),
                "time_stop_bars": _json_compatible(row.get("time_stop_bars")),
                "matched_rule_id": _json_compatible(row.get("matched_rule_id")),
            }
            action_result = {
                "timestamp": _json_compatible(row.get("timestamp")),
                "symbol": _json_compatible(row.get("symbol")),
                "action_raw": _json_compatible(row.get("action")),
                "size": _json_compatible(row.get("size")),
                "stop_loss": _json_compatible(row.get("stop_loss")),
                "take_profit": _json_compatible(row.get("take_profit")),
                "reason": _json_compatible(row.get("reason")),
            }

            score_adjustment_payload = {
                "score_base": _json_compatible(row.get("score_base")),
                "score_adjustment": _json_compatible(row.get("score_adjustment")),
                "score_final": _json_compatible(row.get("score_total")),
                "detail": _json_compatible(row.get("state_adjustment_detail")),
            }
            rule_results_payload = _json_compatible(row.get("rule_scores"))
            if any(
                key in row
                for key in (
                    "rule_traces",
                    "condition_hits",
                    "condition_results",
                    "score_base",
                    "score_adjustment",
                    "state_adjustment_detail",
                    "macd_state",
                )
            ):
                rule_results_payload = {
                    "scores": _json_compatible(row.get("rule_scores")),
                    "rule_trace": _json_compatible(row.get("rule_traces")),
                    "condition_hits": _json_compatible(row.get("condition_hits")),
                    "condition_results": _json_compatible(row.get("condition_results")),
                    "score_adjustment": score_adjustment_payload,
                    "macd_state": _json_compatible(row.get("macd_state")),
                }

            rows.append(
                {
                    "signal_time": row.get("timestamp"),
                    "symbol": str(row.get("symbol", "")),
                    "action_raw": str(row.get("action", "")),
                    "reason": str(row.get("reason", "")),
                    "state": str(row.get("state", "")),
                    "score_total": _json_compatible(row.get("score_total")),
                    "feature_values": feature_values,
                    "required_feature_refs": required_refs,
                    "required_feature_values": required_values,
                    "rule_results": _json_compatible(rule_results_payload),
                    "group_scores": _json_compatible(row.get("group_scores")),
                    "group_weights": _json_compatible(row.get("group_weights")),
                    "signal_decision": signal_decision,
                    "risk_decision": risk_decision,
                    "action_result": action_result,
                }
            )
        output = pd.DataFrame(rows, columns=trace_columns)
        output["signal_time"] = pd.to_datetime(output["signal_time"], utc=True, errors="coerce")
        output = output.dropna(subset=["signal_time"]).sort_values(["signal_time", "symbol"]).reset_index(drop=True)
        return output


__all__ = ["ProfileActionStrategy"]
