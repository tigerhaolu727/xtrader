"""Core strategy protocol objects and shared validation helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import pandas as pd

DEFAULT_STRATEGY_OUTPUT_SCHEMA: tuple[str, ...] = (
    "timestamp",
    "symbol",
    "target_weight",
)
DEFAULT_ACTION_OUTPUT_SCHEMA: tuple[str, ...] = (
    "timestamp",
    "symbol",
    "action",
    "size",
    "stop_loss",
    "take_profit",
    "reason",
)


class TradeAction(str, Enum):
    """Supported action types for single-instrument trading strategies."""

    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT = "EXIT"
    HOLD = "HOLD"
    REVERSE = "REVERSE"

    @classmethod
    def values(cls) -> set[str]:
        return {member.value for member in cls}


def _validate_param_type(name: str, value: Any, expected_type: type[Any]) -> None:
    if expected_type is int and isinstance(value, bool):
        raise TypeError(f"parameter '{name}' must be int, got bool")
    if not isinstance(value, expected_type):
        raise TypeError(f"parameter '{name}' must be {expected_type.__name__}, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """Static strategy contract used by runtime and validation layers."""

    strategy_id: str
    version: str
    required_inputs: tuple[str, ...]
    params_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_schema: tuple[str, ...] = DEFAULT_STRATEGY_OUTPUT_SCHEMA
    tags: tuple[str, ...] = ()

    def resolve_params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        provided = dict(params or {})
        resolved: dict[str, Any] = {}
        for key, rule in self.params_schema.items():
            has_default = "default" in rule
            required = bool(rule.get("required", not has_default))
            if key not in provided:
                if has_default:
                    resolved[key] = rule["default"]
                    continue
                if required:
                    raise ValueError(f"missing required parameter: {key}")
                continue
            value = provided.pop(key)
            if "type" in rule:
                _validate_param_type(key, value, rule["type"])
            if "min" in rule and value < rule["min"]:
                raise ValueError(f"parameter '{key}' must be >= {rule['min']}")
            if "max" in rule and value > rule["max"]:
                raise ValueError(f"parameter '{key}' must be <= {rule['max']}")
            resolved[key] = value
        if provided:
            unknown = ", ".join(sorted(provided))
            raise ValueError(f"unknown parameters for {self.strategy_id}: {unknown}")
        return resolved


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """Runtime strategy context containing universe and input frames."""

    as_of_time: datetime
    universe: tuple[str, ...]
    inputs: dict[str, pd.DataFrame]
    params: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def require_input(self, name: str) -> pd.DataFrame:
        try:
            return self.inputs[name]
        except KeyError as exc:
            raise KeyError(f"missing required input: {name}") from exc


@dataclass(frozen=True, slots=True)
class StrategyResult:
    """Standardized strategy output payload."""

    strategy_id: str
    strategy_version: str
    weights: pd.DataFrame
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def validate_schema(self, expected_schema: tuple[str, ...] | None = None) -> None:
        required = expected_schema or DEFAULT_STRATEGY_OUTPUT_SCHEMA
        missing = [column for column in required if column not in self.weights.columns]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"strategy result missing required columns: {joined}")


@dataclass(frozen=True, slots=True)
class ActionStrategyResult:
    """Standardized action-strategy output payload."""

    strategy_id: str
    strategy_version: str
    actions: pd.DataFrame
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def validate_schema(self, expected_schema: tuple[str, ...] | None = None) -> None:
        required = expected_schema or DEFAULT_ACTION_OUTPUT_SCHEMA
        missing = [column for column in required if column not in self.actions.columns]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"action strategy result missing required columns: {joined}")
        action_values = set(self.actions["action"].dropna().astype(str).unique().tolist()) if "action" in self.actions.columns else set()
        invalid = sorted(action_values.difference(TradeAction.values()))
        if invalid:
            joined = ", ".join(invalid)
            raise ValueError(f"action strategy result contains invalid action values: {joined}")


class BaseStrategy(ABC):
    """Base strategy interface. All concrete strategies must implement this contract."""

    @abstractmethod
    def spec(self) -> StrategySpec:
        """Return static strategy contract."""

    @abstractmethod
    def generate(self, context: StrategyContext) -> StrategyResult:
        """Generate strategy target weights using only context-provided inputs."""


class BaseActionStrategy(ABC):
    """Base interface for event/action driven trading strategies."""

    @abstractmethod
    def spec(self) -> StrategySpec:
        """Return static strategy contract."""

    @abstractmethod
    def generate_actions(self, context: StrategyContext) -> ActionStrategyResult:
        """Generate trading actions using only context-provided inputs."""


__all__ = [
    "ActionStrategyResult",
    "BaseActionStrategy",
    "BaseStrategy",
    "DEFAULT_ACTION_OUTPUT_SCHEMA",
    "DEFAULT_STRATEGY_OUTPUT_SCHEMA",
    "StrategyContext",
    "StrategyResult",
    "StrategySpec",
    "TradeAction",
]
