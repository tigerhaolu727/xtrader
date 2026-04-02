"""Pydantic models for strategy profile v0.3 schema validation."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Timeframe = Annotated[str, StringConstraints(pattern=r"^[0-9]+[smhdw]$")]
StateName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
FeatureRef = Annotated[str, StringConstraints(pattern=r"^f:[^:]+:[^:]+:[^:]+$")]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _ensure_unique(items: list[str], *, field_name: str) -> list[str]:
    seen: set[str] = set()
    for value in items:
        if value in seen:
            raise ValueError(f"{field_name} contains duplicate value: {value}")
        seen.add(value)
    return items


class IndicatorPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: NonEmptyString
    family: NonEmptyString
    params: dict[str, Any]


class AlignmentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["ffill_last_closed"]
    max_staleness_bars_by_tf: dict[Timeframe, Annotated[int, Field(ge=1)]] = Field(default_factory=dict)


class ClassifierPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: FeatureRef
    op: Literal[">", ">=", "<", "<=", "==", "!=", "between"]
    value: float | None = None
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _validate_predicate_payload(self) -> "ClassifierPredicate":
        if self.op == "between":
            if self.min is None or self.max is None:
                raise ValueError("between requires both min and max")
        elif self.value is None:
            raise ValueError("value is required when op is not between")
        return self


class ClassifierRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: Annotated[int, Field(ge=1)]
    target_state: StateName
    conditions: list[ClassifierPredicate] = Field(min_length=1)
    enabled: bool = True


class ClassifierSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: list[FeatureRef] = Field(min_length=1)
    rules: list[ClassifierRule] = Field(min_length=1)
    default_state: StateName

    @field_validator("inputs")
    @classmethod
    def _validate_unique_inputs(cls, value: list[str]) -> list[str]:
        return _ensure_unique(value, field_name="classifier.inputs")


class GroupRuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: NonEmptyString
    score_fn: Literal[
        "trend_score",
        "momentum_score",
        "direction_score",
        "volume_score",
        "pullback_score",
    ]
    input_refs: list[FeatureRef] = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    nan_policy: Literal["neutral_zero"] = "neutral_zero"
    enabled: bool = True


class GroupSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: NonEmptyString
    rules: list[GroupRuleSpec] = Field(min_length=1)
    rule_weights: dict[str, Annotated[float, Field(ge=0.0)]] = Field(min_length=1)
    enabled: bool = True


class RegimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_timeframe: Timeframe
    alignment_policy: AlignmentPolicy
    states: list[StateName] = Field(min_length=1)
    classifier: ClassifierSpec
    groups: list[GroupSpec] = Field(min_length=1)
    state_group_weights: dict[str, dict[str, Annotated[float, Field(ge=0.0)]]]

    @field_validator("states")
    @classmethod
    def _validate_unique_states(cls, value: list[str]) -> list[str]:
        return _ensure_unique(value, field_name="regime_spec.states")


class ScoreRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: Annotated[float | None, Field(ge=-1.0, le=1.0)]
    max: Annotated[float | None, Field(ge=-1.0, le=1.0)]
    min_inclusive: bool = True
    max_inclusive: bool = False


class SignalRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyString
    action: Literal["ENTER_LONG", "ENTER_SHORT", "EXIT", "HOLD"]
    priority_rank: Annotated[int, Field(ge=1)]
    score_range: ScoreRange
    state_allow: list[StateName] | None = None
    state_deny: list[StateName] | None = None
    enabled: bool = True

    @field_validator("state_allow", "state_deny")
    @classmethod
    def _validate_unique_state_filters(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return _ensure_unique(value, field_name="signal_rule.state_filter")


class SignalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_rules: list[SignalRule] = Field(min_length=1)
    exit_rules: list[SignalRule] = Field(min_length=1)
    hold_rules: list[SignalRule] = Field(default_factory=list)
    cooldown_bars: Annotated[int, Field(ge=0)] = 0
    cooldown_scope: Literal["symbol_action"] = "symbol_action"
    reason_code_map: dict[str, NonEmptyString] = Field(min_length=1)


class SizeModelParamsFixedFraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fraction: Annotated[float, Field(gt=0.0, le=1.0)]


class SizeModelFixedFraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["fixed_fraction"]
    params: SizeModelParamsFixedFraction


class StopModelParamsFixedPct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pct: Annotated[float, Field(gt=0.0, le=1.0)]


class StopModelParamsAtrMultiple(BaseModel):
    model_config = ConfigDict(extra="forbid")

    multiple: Annotated[float, Field(gt=0.0)]


class StopModelFixedPct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["fixed_pct"]
    params: StopModelParamsFixedPct


class StopModelAtrMultiple(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["atr_multiple"]
    params: StopModelParamsAtrMultiple


class TakeProfitModelParamsFixedPct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pct: Annotated[float, Field(gt=0.0, le=1.0)]


class TakeProfitModelParamsRrMultiple(BaseModel):
    model_config = ConfigDict(extra="forbid")

    multiple: Annotated[float, Field(gt=0.0)]


class TakeProfitModelFixedPct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["fixed_pct"]
    params: TakeProfitModelParamsFixedPct


class TakeProfitModelRrMultiple(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["rr_multiple"]
    params: TakeProfitModelParamsRrMultiple


class TimeStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bars: Annotated[int, Field(ge=1)]


class PortfolioGuards(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_loss_limit: Annotated[float, Field(ge=0.0, le=1.0)]
    max_concurrent_positions: Annotated[int, Field(ge=1)] = 1


class RoundingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_dp: Annotated[int, Field(ge=0)] = 4
    size_dp: Annotated[int, Field(ge=0)] = 4


SizeModelBlock = SizeModelFixedFraction
StopModelBlock = Annotated[StopModelFixedPct | StopModelAtrMultiple, Field(discriminator="mode")]
TakeProfitModelBlock = Annotated[TakeProfitModelFixedPct | TakeProfitModelRrMultiple, Field(discriminator="mode")]


class RiskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size_model: SizeModelBlock
    stop_model: StopModelBlock
    take_profit_model: TakeProfitModelBlock
    time_stop: TimeStop
    portfolio_guards: PortfolioGuards
    rounding_policy: RoundingPolicy | None = None


class StrategyProfileV03(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["xtrader.strategy_profile.v0.3"]
    strategy_id: NonEmptyString
    version: NonEmptyString
    indicator_plan_by_tf: dict[Timeframe, list[IndicatorPlanItem]]
    regime_spec: RegimeSpec
    signal_spec: SignalSpec
    risk_spec: RiskSpec
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_indicator_plan(self) -> "StrategyProfileV03":
        if not self.indicator_plan_by_tf:
            raise ValueError("indicator_plan_by_tf must be non-empty")
        for timeframe, items in self.indicator_plan_by_tf.items():
            if not items:
                raise ValueError(f"indicator_plan_by_tf[{timeframe}] must contain at least one item")
        return self


__all__ = [
    "StrategyProfileV03",
]
