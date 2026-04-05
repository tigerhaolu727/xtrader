"""Kaufman adaptive moving average indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule

try:  # pragma: no cover - optional acceleration path
    import talib  # type: ignore
except Exception:  # pragma: no cover
    talib = None


class KAMAIndicator(BaseIndicator):
    name = "kama"
    category = "trend"
    required_columns = ("close",)
    param_order = ("er_period", "fast_period", "slow_period")
    params_schema = {
        "er_period": ParamRule(type=int, default=10, min_value=1),
        "fast_period": ParamRule(type=int, default=2, min_value=1),
        "slow_period": ParamRule(type=int, default=30, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        er_period = int(resolved["er_period"])
        fast_period = int(resolved["fast_period"])
        slow_period = int(resolved["slow_period"])

        close = pd.to_numeric(frame["close"], errors="coerce").astype("float64")
        if talib is not None:
            values = pd.Series(talib.KAMA(close.to_numpy(), timeperiod=er_period), index=frame.index, dtype="float64")
        else:
            values = self._compute_fallback(
                close=close,
                er_period=er_period,
                fast_period=fast_period,
                slow_period=slow_period,
            )

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: values}, index=frame.index)

    @staticmethod
    def _compute_fallback(
        *,
        close: pd.Series,
        er_period: int,
        fast_period: int,
        slow_period: int,
    ) -> pd.Series:
        change = (close - close.shift(er_period)).abs()
        volatility = close.diff().abs().rolling(window=er_period, min_periods=er_period).sum()
        er = pd.Series(np.zeros(len(close), dtype="float64"), index=close.index)
        valid_vol = volatility > 0.0
        er.loc[valid_vol] = (change.loc[valid_vol] / volatility.loc[valid_vol]).astype("float64")
        er = er.clip(lower=0.0, upper=1.0)

        fast_sc = 2.0 / (float(fast_period) + 1.0)
        slow_sc = 2.0 / (float(slow_period) + 1.0)
        smooth = (er * (fast_sc - slow_sc) + slow_sc) ** 2

        output = pd.Series(np.nan, index=close.index, dtype="float64")
        if len(close.index) <= er_period:
            return output

        start = int(er_period)
        first_price = float(close.iloc[start])
        if np.isnan(first_price):
            return output
        output.iloc[start] = first_price

        for idx in range(start + 1, len(close.index)):
            price = float(close.iloc[idx])
            if np.isnan(price):
                continue
            prev = float(output.iloc[idx - 1])
            if np.isnan(prev):
                output.iloc[idx] = price
                continue
            sc = float(smooth.iloc[idx])
            if not np.isfinite(sc):
                sc = slow_sc**2
            output.iloc[idx] = prev + (sc * (price - prev))
        return output


__all__ = ["KAMAIndicator"]
