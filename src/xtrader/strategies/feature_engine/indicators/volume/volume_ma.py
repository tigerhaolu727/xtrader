"""Volume moving-average indicator."""

from __future__ import annotations

import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class VolumeMAIndicator(BaseIndicator):
    name = "volume_ma"
    category = "volume"
    required_columns = ("volume",)
    param_order = ("period",)
    params_schema = {
        "period": ParamRule(type=int, default=20, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        resolved = self.resolve_params(params)
        period = int(resolved["period"])

        volume = pd.to_numeric(frame["volume"], errors="coerce")
        values = volume.rolling(window=period, min_periods=period).mean()

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: values}, index=frame.index)


__all__ = ["VolumeMAIndicator"]
