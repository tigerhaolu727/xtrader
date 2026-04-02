"""KD (stochastic) indicator family."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class KDIndicator(BaseIndicator):
    name = "kd"
    category = "oscillator"
    required_columns = ("high", "low", "close")
    param_order = ("k_period", "k_smooth", "d_period")
    params_schema = {
        "k_period": ParamRule(type=int, default=9, min_value=1),
        "k_smooth": ParamRule(type=int, default=3, min_value=1),
        "d_period": ParamRule(type=int, default=3, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        k_period = int(resolved["k_period"])
        k_smooth = int(resolved["k_smooth"])
        d_period = int(resolved["d_period"])

        high = pd.to_numeric(frame["high"], errors="coerce")
        low = pd.to_numeric(frame["low"], errors="coerce")
        close = pd.to_numeric(frame["close"], errors="coerce")

        low_n = low.rolling(window=k_period, min_periods=k_period).min()
        high_n = high.rolling(window=k_period, min_periods=k_period).max()
        denom = (high_n - low_n).replace(0.0, np.nan)
        raw_k = ((close - low_n) / denom) * 100.0
        k = raw_k.rolling(window=k_smooth, min_periods=k_smooth).mean()
        d = k.rolling(window=d_period, min_periods=d_period).mean()
        j = 3.0 * k - 2.0 * d
        j = j.replace([np.inf, -np.inf], np.nan)

        cols = self.build_output_columns(resolved, suffixes=("k", "d", "j"))
        return pd.DataFrame(
            {
                cols[0]: k,
                cols[1]: d,
                cols[2]: j,
            },
            index=frame.index,
        )


__all__ = ["KDIndicator"]
