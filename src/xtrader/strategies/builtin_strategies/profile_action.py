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


def _default_profile_path() -> Path:
    return Path(__file__).resolve().parents[4] / "configs/strategy-profiles/five_min_regime_momentum/v0.3.json"


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
        )
        result.validate_schema(self.spec().output_schema)
        return result


__all__ = ["ProfileActionStrategy"]
