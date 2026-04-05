"""MESA adaptive moving average indicator (MAMA/FAMA)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.errors import xtr018_error
from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule

try:  # pragma: no cover - optional acceleration path
    import talib  # type: ignore
except Exception:  # pragma: no cover
    talib = None


class MAMAIndicator(BaseIndicator):
    name = "mama"
    category = "trend"
    required_columns = ("close",)
    param_order = ("fast_limit", "slow_limit")
    params_schema = {
        "fast_limit": ParamRule(type=float, default=0.5, min_value=0.01, max_value=1.0),
        "slow_limit": ParamRule(type=float, default=0.05, min_value=0.001, max_value=1.0),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        fast_limit = float(resolved["fast_limit"])
        slow_limit = float(resolved["slow_limit"])
        if fast_limit <= slow_limit:
            raise xtr018_error("PARAM_OUT_OF_RANGE", "mama requires fast_limit > slow_limit")

        close = pd.to_numeric(frame["close"], errors="coerce").astype("float64")
        if talib is not None:
            mama_arr, fama_arr = talib.MAMA(
                close.to_numpy(),
                fastlimit=fast_limit,
                slowlimit=slow_limit,
            )
            mama = pd.Series(mama_arr, index=frame.index, dtype="float64")
            fama = pd.Series(fama_arr, index=frame.index, dtype="float64")
        else:
            mama, fama = self._compute_fallback(
                close=close,
                fast_limit=fast_limit,
                slow_limit=slow_limit,
            )

        cols = self.build_output_columns(resolved, suffixes=("mama", "fama"))
        return pd.DataFrame(
            {
                cols[0]: mama,
                cols[1]: fama,
            },
            index=frame.index,
        )

    @staticmethod
    def _compute_fallback(
        *,
        close: pd.Series,
        fast_limit: float,
        slow_limit: float,
        er_period: int = 10,
    ) -> tuple[pd.Series, pd.Series]:
        change = (close - close.shift(er_period)).abs()
        volatility = close.diff().abs().rolling(window=er_period, min_periods=er_period).sum()
        er = pd.Series(np.zeros(len(close), dtype="float64"), index=close.index)
        valid = volatility > 0.0
        er.loc[valid] = (change.loc[valid] / volatility.loc[valid]).astype("float64")
        er = er.clip(lower=0.0, upper=1.0)

        alpha = (er * (fast_limit - slow_limit) + slow_limit).clip(lower=slow_limit, upper=fast_limit)
        mama = pd.Series(np.nan, index=close.index, dtype="float64")
        fama = pd.Series(np.nan, index=close.index, dtype="float64")
        if close.empty:
            return mama, fama

        first_idx = close.first_valid_index()
        if first_idx is None:
            return mama, fama
        first_pos = int(close.index.get_loc(first_idx))
        first_price = float(close.iloc[first_pos])
        mama.iloc[first_pos] = first_price
        fama.iloc[first_pos] = first_price

        for idx in range(first_pos + 1, len(close.index)):
            price = float(close.iloc[idx])
            if np.isnan(price):
                continue
            a = float(alpha.iloc[idx]) if np.isfinite(alpha.iloc[idx]) else slow_limit
            prev_mama = float(mama.iloc[idx - 1])
            prev_fama = float(fama.iloc[idx - 1])
            if np.isnan(prev_mama):
                prev_mama = price
            if np.isnan(prev_fama):
                prev_fama = price
            cur_mama = prev_mama + a * (price - prev_mama)
            cur_fama = prev_fama + (0.5 * a) * (cur_mama - prev_fama)
            mama.iloc[idx] = cur_mama
            fama.iloc[idx] = cur_fama
        return mama, fama


__all__ = ["MAMAIndicator"]
