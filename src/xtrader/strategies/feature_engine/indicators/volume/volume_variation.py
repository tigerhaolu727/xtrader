"""Volume variation-rate indicator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


class VolumeVariationIndicator(BaseIndicator):
    name = "volume_variation"
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
        base = volume.rolling(window=period, min_periods=period).mean()
        variation = (volume / base.replace(0.0, np.nan)) - 1.0

        output_col = self.build_output_columns(resolved)[0]
        return pd.DataFrame({output_col: variation}, index=frame.index)


__all__ = ["VolumeVariationIndicator"]
