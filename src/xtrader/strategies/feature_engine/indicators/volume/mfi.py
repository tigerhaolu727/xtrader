"""Money flow index indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule

try:  # pragma: no cover - optional acceleration path
    import talib  # type: ignore
except Exception:  # pragma: no cover
    talib = None


class MFIIndicator(BaseIndicator):
    name = "mfi"
    category = "volume"
    required_columns = ("high", "low", "close", "volume")
    param_order = ("period",)
    params_schema = {
        "period": ParamRule(type=int, default=14, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        period = int(resolved["period"])

        high = pd.to_numeric(frame["high"], errors="coerce").astype("float64")
        low = pd.to_numeric(frame["low"], errors="coerce").astype("float64")
        close = pd.to_numeric(frame["close"], errors="coerce").astype("float64")
        volume = pd.to_numeric(frame["volume"], errors="coerce").astype("float64")

        if talib is not None:
            values = pd.Series(
                talib.MFI(high.to_numpy(), low.to_numpy(), close.to_numpy(), volume.to_numpy(), timeperiod=period),
                index=frame.index,
                dtype="float64",
            )
        else:
            typical_price = (high + low + close) / 3.0
            money_flow = typical_price * volume
            delta_tp = typical_price.diff()
            positive_flow = money_flow.where(delta_tp > 0.0, 0.0)
            negative_flow = money_flow.where(delta_tp < 0.0, 0.0).abs()

            pos_sum = positive_flow.rolling(window=period, min_periods=period).sum()
            neg_sum = negative_flow.rolling(window=period, min_periods=period).sum()
            ratio = pos_sum / neg_sum.replace(0.0, np.nan)
            values = 100.0 - (100.0 / (1.0 + ratio))
            values = values.mask((neg_sum == 0.0) & (pos_sum > 0.0), 100.0)
            values = values.mask((neg_sum == 0.0) & (pos_sum == 0.0), 50.0)

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: values}, index=frame.index)


__all__ = ["MFIIndicator"]
