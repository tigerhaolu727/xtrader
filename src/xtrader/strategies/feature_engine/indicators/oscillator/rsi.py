"""Relative strength index indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class RSIIndicator(BaseIndicator):
    name = "rsi"
    category = "oscillator"
    required_columns = ("close",)
    param_order = ("period",)
    params_schema = {
        "period": ParamRule(type=int, default=14, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        period = int(resolved["period"])
        close = pd.to_numeric(frame["close"], errors="coerce")

        delta = close.diff()
        gains = delta.clip(lower=0.0)
        losses = -delta.clip(upper=0.0)

        avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: rsi}, index=frame.index)


__all__ = ["RSIIndicator"]
