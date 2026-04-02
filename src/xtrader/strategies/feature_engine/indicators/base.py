"""Base indicator abstraction and shared parameter helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
from typing import Any

import pandas as pd

from xtrader.strategies.feature_engine.errors import xtr018_error


@dataclass(frozen=True, slots=True)
class ParamRule:
    """Validation rule for one indicator parameter."""

    type: type[Any]
    default: Any | None = None
    required: bool = False
    min_value: float | int | None = None
    max_value: float | int | None = None


class BaseIndicator(ABC):
    """Unified indicator interface used by feature-engine pipeline."""

    name: str
    category: str
    required_columns: tuple[str, ...]
    param_order: tuple[str, ...]
    params_schema: dict[str, ParamRule]

    def resolve_params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(params or {})
        resolved: dict[str, Any] = {}
        for key, rule in self.params_schema.items():
            has_default = rule.default is not None
            required = bool(rule.required or not has_default)
            if key not in payload:
                if has_default:
                    resolved[key] = rule.default
                    continue
                if required:
                    raise xtr018_error("PARAM_MISSING_REQUIRED", f"{self.name}.{key}")
                continue
            value = payload.pop(key)
            self._validate_type(name=key, value=value, expected=rule.type)
            if rule.min_value is not None and value < rule.min_value:
                raise xtr018_error("PARAM_OUT_OF_RANGE", f"{self.name}.{key} < {rule.min_value}")
            if rule.max_value is not None and value > rule.max_value:
                raise xtr018_error("PARAM_OUT_OF_RANGE", f"{self.name}.{key} > {rule.max_value}")
            resolved[key] = value

        if payload:
            unknown = ",".join(sorted(payload))
            raise xtr018_error("PARAM_UNKNOWN", f"{self.name}: {unknown}")

        for key in self.param_order:
            if key not in resolved:
                raise xtr018_error("PARAM_MISSING_REQUIRED", f"{self.name}.{key}")
        return resolved

    def build_prefix(self, resolved_params: dict[str, Any]) -> str:
        values: list[str] = []
        for key in self.param_order:
            values.append(_format_param_value_for_column(resolved_params[key]))
        suffix = "_".join(values)
        return f"{self.name}_{suffix}" if suffix else self.name

    def build_output_columns(self, resolved_params: dict[str, Any], *, suffixes: tuple[str, ...] = ()) -> tuple[str, ...]:
        prefix = self.build_prefix(resolved_params)
        if not suffixes:
            return (prefix,)
        return tuple(f"{prefix}_{suffix}" for suffix in suffixes)

    @abstractmethod
    def compute(self, frame: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Compute indicator features and return DataFrame aligned to input index."""

    @staticmethod
    def _validate_type(*, name: str, value: Any, expected: type[Any]) -> None:
        if expected is int and isinstance(value, bool):
            raise xtr018_error("PARAM_INVALID_TYPE", f"{name} expects int, got bool")
        if expected is float and isinstance(value, bool):
            raise xtr018_error("PARAM_INVALID_TYPE", f"{name} expects float, got bool")
        if expected is float and isinstance(value, int):
            return
        if not isinstance(value, expected):
            raise xtr018_error("PARAM_INVALID_TYPE", f"{name} expects {expected.__name__}, got {type(value).__name__}")


def format_param_value_for_column(value: Any) -> str:
    return _format_param_value_for_column(value)


def _format_param_value_for_column(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise xtr018_error("PARAM_INVALID_TYPE", f"non-finite float parameter: {value}")
        rounded = round(float(value), 2)
        if rounded.is_integer():
            return str(int(rounded))
        return f"{rounded:.2f}"
    return str(value)


__all__ = [
    "BaseIndicator",
    "ParamRule",
    "format_param_value_for_column",
]
