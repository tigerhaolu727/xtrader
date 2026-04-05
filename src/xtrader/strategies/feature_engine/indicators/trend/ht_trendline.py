"""Hilbert transform trendline indicator."""

from __future__ import annotations

import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator

try:  # pragma: no cover - optional acceleration path
    import talib  # type: ignore
except Exception:  # pragma: no cover
    talib = None


class HTTrendlineIndicator(BaseIndicator):
    name = "ht_trendline"
    category = "trend"
    required_columns = ("close",)
    param_order = ()
    params_schema = {}

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        close = pd.to_numeric(frame["close"], errors="coerce").astype("float64")
        if talib is not None:
            values = pd.Series(
                talib.HT_TRENDLINE(close.to_numpy()),
                index=frame.index,
                dtype="float64",
            )
        else:
            # Fallback proxy when TA-Lib is unavailable.
            values = close.ewm(span=7, adjust=False, min_periods=7).mean()

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: values}, index=frame.index)


__all__ = ["HTTrendlineIndicator"]
