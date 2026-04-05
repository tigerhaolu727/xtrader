"""TRIX indicator (triple EMA momentum oscillator)."""

from __future__ import annotations

import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule

try:  # pragma: no cover - optional acceleration path
    import talib  # type: ignore
except Exception:  # pragma: no cover
    talib = None


class TRIXIndicator(BaseIndicator):
    name = "trix"
    category = "trend"
    required_columns = ("close",)
    param_order = ("period",)
    params_schema = {
        "period": ParamRule(type=int, default=15, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        period = int(resolved["period"])
        close = pd.to_numeric(frame["close"], errors="coerce").astype("float64")

        if talib is not None:
            values = pd.Series(talib.TRIX(close.to_numpy(), timeperiod=period), index=frame.index, dtype="float64")
        else:
            ema1 = close.ewm(span=period, adjust=False, min_periods=period).mean()
            ema2 = ema1.ewm(span=period, adjust=False, min_periods=period).mean()
            ema3 = ema2.ewm(span=period, adjust=False, min_periods=period).mean()
            values = ema3.pct_change(fill_method=None) * 100.0

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: values}, index=frame.index)


__all__ = ["TRIXIndicator"]
