"""Directional movement indicator (plus_di/minus_di/adx)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class DMIIndicator(BaseIndicator):
    name = "dmi"
    category = "trend"
    required_columns = ("high", "low", "close")
    param_order = ("di_period", "adx_period")
    params_schema = {
        "di_period": ParamRule(type=int, default=14, min_value=1),
        "adx_period": ParamRule(type=int, default=14, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        di_period = int(resolved["di_period"])
        adx_period = int(resolved["adx_period"])

        high = pd.to_numeric(frame["high"], errors="coerce")
        low = pd.to_numeric(frame["low"], errors="coerce")
        close = pd.to_numeric(frame["close"], errors="coerce")

        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=frame.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=frame.index)

        tr_components = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        )
        tr = tr_components.max(axis=1)

        atr = tr.ewm(alpha=1 / di_period, adjust=False, min_periods=di_period).mean()
        plus_dm_smooth = plus_dm.ewm(alpha=1 / di_period, adjust=False, min_periods=di_period).mean()
        minus_dm_smooth = minus_dm.ewm(alpha=1 / di_period, adjust=False, min_periods=di_period).mean()

        plus_di = 100.0 * plus_dm_smooth / atr.replace(0.0, np.nan)
        minus_di = 100.0 * minus_dm_smooth / atr.replace(0.0, np.nan)
        dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)
        adx = dx.ewm(alpha=1 / adx_period, adjust=False, min_periods=adx_period).mean()

        cols = self.build_output_columns(resolved, suffixes=("plus_di", "minus_di", "adx"))
        return pd.DataFrame(
            {
                cols[0]: plus_di,
                cols[1]: minus_di,
                cols[2]: adx,
            },
            index=frame.index,
        )


__all__ = ["DMIIndicator"]
