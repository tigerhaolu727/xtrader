"""Bollinger bands indicator family."""

from __future__ import annotations

import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class BollingerIndicator(BaseIndicator):
    name = "bollinger"
    category = "volatility"
    required_columns = ("close",)
    param_order = ("period", "std")
    params_schema = {
        "period": ParamRule(type=int, default=20, min_value=1),
        "std": ParamRule(type=float, default=2.0, min_value=0.0),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        period = int(resolved["period"])
        std_mult = float(resolved["std"])

        close = pd.to_numeric(frame["close"], errors="coerce")
        mid = close.rolling(window=period, min_periods=period).mean()
        stdev = close.rolling(window=period, min_periods=period).std(ddof=0)
        up = mid + std_mult * stdev
        low = mid - std_mult * stdev

        cols = self.build_output_columns(resolved, suffixes=("mid", "up", "low"))
        return pd.DataFrame(
            {
                cols[0]: mid,
                cols[1]: up,
                cols[2]: low,
            },
            index=frame.index,
        )


__all__ = ["BollingerIndicator"]
