"""Fractal adaptive moving average indicator."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.errors import xtr018_error
from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule

_FRAMA_ALPHA_SCALE = 4.6


class FRAMAIndicator(BaseIndicator):
    name = "frama"
    category = "trend"
    required_columns = ("high", "low", "close")
    param_order = ("window", "alpha_min", "alpha_max")
    params_schema = {
        "window": ParamRule(type=int, default=16, min_value=2),
        "alpha_min": ParamRule(type=float, default=0.01, min_value=0.001, max_value=1.0),
        "alpha_max": ParamRule(type=float, default=1.0, min_value=0.01, max_value=1.0),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        window = int(resolved["window"])
        alpha_min = float(resolved["alpha_min"])
        alpha_max = float(resolved["alpha_max"])
        if alpha_max < alpha_min:
            raise xtr018_error("PARAM_OUT_OF_RANGE", "frama requires alpha_max >= alpha_min")
        if window % 2 != 0:
            raise xtr018_error("PARAM_OUT_OF_RANGE", "frama.window must be even")

        high = pd.to_numeric(frame["high"], errors="coerce").astype("float64")
        low = pd.to_numeric(frame["low"], errors="coerce").astype("float64")
        close = pd.to_numeric(frame["close"], errors="coerce").astype("float64")

        values = self._compute_frama(
            high=high,
            low=low,
            close=close,
            window=window,
            alpha_min=alpha_min,
            alpha_max=alpha_max,
        )
        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: values}, index=frame.index)

    @staticmethod
    def _compute_frama(
        *,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int,
        alpha_min: float,
        alpha_max: float,
    ) -> pd.Series:
        half = window // 2
        out = pd.Series(np.nan, index=close.index, dtype="float64")
        if len(close.index) < window:
            return out

        first_idx = window - 1
        first_price = float(close.iloc[first_idx])
        if not np.isnan(first_price):
            out.iloc[first_idx] = first_price

        log2 = math.log(2.0)
        for idx in range(first_idx + 1, len(close.index)):
            h_window = high.iloc[idx - window + 1 : idx + 1]
            l_window = low.iloc[idx - window + 1 : idx + 1]
            c = float(close.iloc[idx])
            if np.isnan(c) or h_window.isna().any() or l_window.isna().any():
                continue

            n1 = (float(h_window.iloc[:half].max()) - float(l_window.iloc[:half].min())) / float(half)
            n2 = (float(h_window.iloc[half:].max()) - float(l_window.iloc[half:].min())) / float(half)
            n3 = (float(h_window.max()) - float(l_window.min())) / float(window)

            if n1 <= 0.0 or n2 <= 0.0 or n3 <= 0.0:
                dim = 1.0
            else:
                dim = (math.log(n1 + n2) - math.log(n3)) / log2
            alpha = math.exp(-_FRAMA_ALPHA_SCALE * (dim - 1.0))
            alpha = float(min(alpha_max, max(alpha_min, alpha)))

            prev = float(out.iloc[idx - 1])
            if np.isnan(prev):
                prev = c
            out.iloc[idx] = prev + alpha * (c - prev)
        return out


__all__ = ["FRAMAIndicator"]
