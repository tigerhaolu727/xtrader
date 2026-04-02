"""Frozen score_fn registry for strategy profile v0.3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


NumberKind = Literal["number", "integer"]


@dataclass(frozen=True, slots=True)
class ParamSpec:
    kind: NumberKind
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    exclusive_maximum: bool = False


@dataclass(frozen=True, slots=True)
class ScoreFnSpec:
    input_roles: tuple[str, ...]
    params: dict[str, ParamSpec]


SCORE_FN_REGISTRY_V03: dict[str, ScoreFnSpec] = {
    "trend_score": ScoreFnSpec(
        input_roles=("ema_fast", "ema_slow", "atr_main"),
        params={"atr_scale": ParamSpec(kind="number", minimum=0.0, exclusive_minimum=True)},
    ),
    "momentum_score": ScoreFnSpec(
        input_roles=("macd_hist",),
        params={"std_window": ParamSpec(kind="integer", minimum=10.0)},
    ),
    "direction_score": ScoreFnSpec(
        input_roles=("plus_di", "minus_di", "adx"),
        params={
            "adx_floor": ParamSpec(kind="number", minimum=0.0, maximum=100.0),
            "adx_span": ParamSpec(kind="number", minimum=0.0, exclusive_minimum=True),
        },
    ),
    "volume_score": ScoreFnSpec(
        input_roles=("volume_variation", "ema_fast", "ema_slow", "atr_main", "macd_hist"),
        params={
            "trend_mix": ParamSpec(kind="number", minimum=0.0, maximum=1.0),
            "vol_scale": ParamSpec(kind="number", minimum=0.0, exclusive_minimum=True),
            "atr_scale": ParamSpec(kind="number", minimum=0.0, exclusive_minimum=True),
        },
    ),
    "pullback_score": ScoreFnSpec(
        input_roles=("close", "ema_fast", "ema_slow", "atr_main"),
        params={"dev_scale": ParamSpec(kind="number", minimum=0.0, exclusive_minimum=True)},
    ),
}


__all__ = ["ParamSpec", "SCORE_FN_REGISTRY_V03", "ScoreFnSpec"]
