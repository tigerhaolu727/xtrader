"""Williams %R indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class WRIndicator(BaseIndicator):
    name = "wr"
    category = "oscillator"
    required_columns = ("high", "low", "close")
    param_order = ("period",)
    params_schema = {
        "period": ParamRule(type=int, default=14, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        period = int(resolved["period"])

        high = pd.to_numeric(frame["high"], errors="coerce")
        low = pd.to_numeric(frame["low"], errors="coerce")
        close = pd.to_numeric(frame["close"], errors="coerce")

        highest = high.rolling(window=period, min_periods=period).max()
        lowest = low.rolling(window=period, min_periods=period).min()
        denom = (highest - lowest).replace(0.0, np.nan)
        wr = (-100.0 * (highest - close) / denom).replace([np.inf, -np.inf], np.nan)

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: wr}, index=frame.index)


__all__ = ["WRIndicator"]
