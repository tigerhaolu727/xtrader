"""Average true range indicator."""

from __future__ import annotations

import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class ATRIndicator(BaseIndicator):
    name = "atr"
    category = "volatility"
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

        tr_components = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        )
        tr = tr_components.max(axis=1)
        atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: atr}, index=frame.index)


__all__ = ["ATRIndicator"]
