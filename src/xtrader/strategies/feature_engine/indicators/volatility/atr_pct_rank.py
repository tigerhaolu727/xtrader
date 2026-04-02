"""Rolling percentile rank of ATR values."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


def _pct_rank_last(values: np.ndarray) -> float:
    # Require a fully valid window so warmup behavior is deterministic.
    if np.isnan(values).any():
        return float("nan")
    last = values[-1]
    return float(np.mean(values <= last))


class ATRPctRankIndicator(BaseIndicator):
    name = "atr_pct_rank"
    category = "volatility"
    required_columns = ("high", "low", "close")
    param_order = ("window",)
    params_schema = {
        "window": ParamRule(type=int, default=252, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        window = int(resolved["window"])
        atr_period = 14

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
        atr = tr.ewm(alpha=1 / atr_period, adjust=False, min_periods=atr_period).mean()
        pct_rank = atr.rolling(window=window, min_periods=window).apply(_pct_rank_last, raw=True)

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: pct_rank}, index=frame.index)


__all__ = ["ATRPctRankIndicator"]

