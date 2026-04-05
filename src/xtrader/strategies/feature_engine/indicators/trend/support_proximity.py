"""Support/resistance proximity derived features for Signal V1."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.errors import xtr018_error
from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


def _nearest_level(candidates: pd.DataFrame, close: pd.Series, *, side: str) -> pd.Series:
    values = candidates.to_numpy(dtype="float64")
    close_values = pd.to_numeric(close, errors="coerce").to_numpy(dtype="float64")
    out = np.full(len(close_values), np.nan, dtype="float64")

    for idx in range(len(close_values)):
        c = close_values[idx]
        row = values[idx]
        if not np.isfinite(c):
            continue
        finite = np.isfinite(row)
        if not finite.any():
            continue

        if side == "support":
            below = finite & (row <= c)
            if below.any():
                out[idx] = float(np.nanmax(row[below]))
                continue
        elif side == "resistance":
            above = finite & (row >= c)
            if above.any():
                out[idx] = float(np.nanmin(row[above]))
                continue

        # Fallback: choose nearest finite level by absolute distance.
        row_finite = row[finite]
        nearest_pos = int(np.argmin(np.abs(row_finite - c)))
        out[idx] = float(row_finite[nearest_pos])

    return pd.Series(out, index=close.index, dtype="float64")


def _strength_code(distance_pct: pd.Series, *, strong_pct: float, medium_pct: float, weak_pct: float) -> pd.Series:
    arr = pd.to_numeric(distance_pct, errors="coerce").to_numpy(dtype="float64")
    code = np.zeros(len(arr), dtype="float64")
    finite = np.isfinite(arr)
    code[finite & (arr <= weak_pct)] = 1.0
    code[finite & (arr <= medium_pct)] = 2.0
    code[finite & (arr <= strong_pct)] = 3.0
    return pd.Series(code, index=distance_pct.index, dtype="float64")


class SupportProximityIndicator(BaseIndicator):
    name = "support_proximity"
    category = "trend"
    required_columns = ("high", "low", "close")
    param_order = ("lookback", "round_step", "strong_pct", "medium_pct", "weak_pct")
    params_schema = {
        "lookback": ParamRule(type=int, default=20, min_value=2),
        "round_step": ParamRule(type=float, default=100.0, min_value=0.0),
        "strong_pct": ParamRule(type=float, default=0.3, min_value=0.0),
        "medium_pct": ParamRule(type=float, default=0.8, min_value=0.0),
        "weak_pct": ParamRule(type=float, default=1.5, min_value=0.0),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        lookback = int(resolved["lookback"])
        round_step = float(resolved["round_step"])
        strong_pct = float(resolved["strong_pct"])
        medium_pct = float(resolved["medium_pct"])
        weak_pct = float(resolved["weak_pct"])

        if round_step <= 0.0:
            raise xtr018_error("PARAM_OUT_OF_RANGE", "support_proximity.round_step > 0")
        if not (strong_pct <= medium_pct <= weak_pct):
            raise xtr018_error(
                "PARAM_OUT_OF_RANGE",
                "support_proximity threshold order requires strong_pct <= medium_pct <= weak_pct",
            )

        high = pd.to_numeric(frame["high"], errors="coerce").astype("float64")
        low = pd.to_numeric(frame["low"], errors="coerce").astype("float64")
        close = pd.to_numeric(frame["close"], errors="coerce").astype("float64")

        ema7 = close.ewm(span=7, adjust=False, min_periods=7).mean()
        ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
        ema60 = close.ewm(span=60, adjust=False, min_periods=60).mean()
        ema200 = close.ewm(span=200, adjust=False, min_periods=200).mean()
        prev_high = high.rolling(window=lookback, min_periods=lookback).max().shift(1)
        prev_low = low.rolling(window=lookback, min_periods=lookback).min().shift(1)
        round_number = (close / round_step).round() * round_step

        support_candidates = pd.concat([ema7, ema20, ema60, ema200, prev_low, round_number], axis=1)
        resistance_candidates = pd.concat([ema7, ema20, ema60, ema200, prev_high, round_number], axis=1)
        nearest_support = _nearest_level(support_candidates, close, side="support")
        nearest_resistance = _nearest_level(resistance_candidates, close, side="resistance")

        close_abs = close.abs().replace(0.0, np.nan)
        support_distance_pct = ((close - nearest_support).abs() / close_abs * 100.0).astype("float64")
        resistance_distance_pct = ((close - nearest_resistance).abs() / close_abs * 100.0).astype("float64")
        support_strength_code = _strength_code(
            support_distance_pct,
            strong_pct=strong_pct,
            medium_pct=medium_pct,
            weak_pct=weak_pct,
        )
        resistance_strength_code = _strength_code(
            resistance_distance_pct,
            strong_pct=strong_pct,
            medium_pct=medium_pct,
            weak_pct=weak_pct,
        )

        cols = self.build_output_columns(
            resolved,
            suffixes=(
                "nearest_support_level",
                "nearest_resistance_level",
                "support_distance_pct",
                "resistance_distance_pct",
                "support_strength_code",
                "resistance_strength_code",
            ),
        )
        return pd.DataFrame(
            {
                cols[0]: nearest_support,
                cols[1]: nearest_resistance,
                cols[2]: support_distance_pct,
                cols[3]: resistance_distance_pct,
                cols[4]: support_strength_code,
                cols[5]: resistance_strength_code,
            },
            index=frame.index,
        )


__all__ = ["SupportProximityIndicator"]
