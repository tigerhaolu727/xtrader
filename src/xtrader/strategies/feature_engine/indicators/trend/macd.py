"""MACD indicator (line/signal/hist)."""

from __future__ import annotations

import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class MACDIndicator(BaseIndicator):
    name = "macd"
    category = "trend"
    required_columns = ("close",)
    param_order = ("fast", "slow", "signal")
    params_schema = {
        "fast": ParamRule(type=int, default=12, min_value=1),
        "slow": ParamRule(type=int, default=26, min_value=1),
        "signal": ParamRule(type=int, default=9, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        fast = int(resolved["fast"])
        slow = int(resolved["slow"])
        signal = int(resolved["signal"])
        close = pd.to_numeric(frame["close"], errors="coerce")

        ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
        ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
        line = ema_fast - ema_slow
        signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
        hist = line - signal_line

        cols = self.build_output_columns(resolved, suffixes=("line", "signal", "hist"))
        return pd.DataFrame(
            {
                cols[0]: line,
                cols[1]: signal_line,
                cols[2]: hist,
            },
            index=frame.index,
        )


__all__ = ["MACDIndicator"]
