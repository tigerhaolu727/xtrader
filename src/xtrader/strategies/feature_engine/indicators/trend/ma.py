"""Simple moving average indicator."""

from __future__ import annotations

import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class MAIndicator(BaseIndicator):
    name = "ma"
    category = "trend"
    required_columns = ("close",)
    param_order = ("period",)
    params_schema = {
        "period": ParamRule(type=int, default=20, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        period = int(resolved["period"])
        output_col = self.build_output_columns(resolved)[0]
        values = pd.to_numeric(frame["close"], errors="coerce").rolling(window=period, min_periods=period).mean()
        return pd.DataFrame({output_col: values}, index=frame.index)


__all__ = ["MAIndicator"]
