"""MACD derived state indicator family for Signal V1 feature-first flow."""

from __future__ import annotations

import numpy as np
import pandas as pd

from xtrader.strategies.feature_engine.errors import xtr018_error
from xtrader.strategies.feature_engine.indicators.base import BaseIndicator, ParamRule


def _consecutive_true(flag: pd.Series, bars: int) -> pd.Series:
    if bars <= 1:
        return flag.fillna(False)
    hit_count = flag.astype("float64").rolling(window=bars, min_periods=bars).sum()
    return (hit_count >= float(bars)).fillna(False)


class MACDStateIndicator(BaseIndicator):
    name = "macd_state"
    category = "trend"
    required_columns = ("close",)
    param_order = ("source_instance_id", "near_gap_pct", "near_gap_abs", "slope_min", "narrow_bars")
    params_schema = {
        "source_instance_id": ParamRule(type=str, required=True),
        "near_gap_pct": ParamRule(type=float, default=0.0015, min_value=0.0),
        "near_gap_abs": ParamRule(type=float, default=0.0, min_value=0.0),
        "slope_min": ParamRule(type=float, default=0.0, min_value=0.0),
        "narrow_bars": ParamRule(type=int, default=2, min_value=1),
    }

    def compute(self, frame: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        payload = dict(params or {})
        source_line_col = str(payload.pop("__source_line_col", "")).strip()
        source_signal_col = str(payload.pop("__source_signal_col", "")).strip()
        source_hist_col = str(payload.pop("__source_hist_col", "")).strip()
        resolved = self.resolve_params(payload)

        if not source_line_col or source_line_col not in frame.columns:
            raise xtr018_error("SOURCE_COLUMN_MISSING", f"macd_state.line:{source_line_col or '<empty>'}")
        if not source_signal_col or source_signal_col not in frame.columns:
            raise xtr018_error("SOURCE_COLUMN_MISSING", f"macd_state.signal:{source_signal_col or '<empty>'}")
        if not source_hist_col or source_hist_col not in frame.columns:
            raise xtr018_error("SOURCE_COLUMN_MISSING", f"macd_state.hist:{source_hist_col or '<empty>'}")

        near_gap_pct = float(resolved["near_gap_pct"])
        near_gap_abs = float(resolved["near_gap_abs"])
        slope_min = float(resolved["slope_min"])
        narrow_bars = int(resolved["narrow_bars"])

        close = pd.to_numeric(frame["close"], errors="coerce").astype("float64")
        line = pd.to_numeric(frame[source_line_col], errors="coerce").astype("float64")
        signal_line = pd.to_numeric(frame[source_signal_col], errors="coerce").astype("float64")
        hist = pd.to_numeric(frame[source_hist_col], errors="coerce").astype("float64")

        gap = (line - signal_line).astype("float64")
        gap_slope = (gap - gap.shift(1)).astype("float64")
        close_abs = close.abs().replace(0.0, np.nan)
        gap_pct = (gap.abs() / close_abs).astype("float64")

        near_by_pct = gap_pct <= near_gap_pct
        near_by_abs = pd.Series(False, index=frame.index, dtype="bool")
        if near_gap_abs > 0.0:
            near_by_abs = gap.abs() <= near_gap_abs
        near = (near_by_pct | near_by_abs).fillna(False)

        near_golden = (near & (gap < 0.0) & (gap_slope >= slope_min)).fillna(False)
        near_dead = (near & (gap > 0.0) & (gap_slope <= -slope_min)).fillna(False)

        golden_expand = ((gap > 0.0) & (gap_slope > slope_min)).fillna(False)
        dead_expand = ((gap < 0.0) & (gap_slope < -slope_min)).fillna(False)

        green_narrow_step = ((hist < 0.0) & (hist.shift(1) < 0.0) & (hist.abs() < hist.shift(1).abs())).fillna(False)
        red_narrow_step = ((hist > 0.0) & (hist.shift(1) > 0.0) & (hist.abs() < hist.shift(1).abs())).fillna(False)
        green_narrow = _consecutive_true(green_narrow_step, narrow_bars)
        red_narrow = _consecutive_true(red_narrow_step, narrow_bars)

        # state_code_num:
        # 0 NONE
        # 1 NEAR_GOLDEN
        # 2 NEAR_DEAD
        # 3 GOLDEN_EXPAND
        # 4 DEAD_EXPAND
        # 5 GREEN_NARROW
        # 6 RED_NARROW
        state_code_num = pd.Series(0.0, index=frame.index, dtype="float64")
        state_code_num.loc[red_narrow] = 6.0
        state_code_num.loc[green_narrow] = 5.0
        state_code_num.loc[dead_expand] = 4.0
        state_code_num.loc[golden_expand] = 3.0
        state_code_num.loc[near_dead] = 2.0
        state_code_num.loc[near_golden] = 1.0

        near_cross_num = pd.Series(0.0, index=frame.index, dtype="float64")
        near_cross_num.loc[near_golden] = 1.0
        near_cross_num.loc[near_dead] = -1.0

        cols = self.build_output_columns(
            resolved,
            suffixes=(
                "state_code_num",
                "near_cross_num",
                "near_golden_flag",
                "near_dead_flag",
                "reject_long_flag",
                "reject_short_flag",
                "gap",
                "gap_slope",
                "gap_pct",
                "green_narrow_2_flag",
                "red_narrow_2_flag",
            ),
        )
        return pd.DataFrame(
            {
                cols[0]: state_code_num,
                cols[1]: near_cross_num,
                cols[2]: near_golden.astype("float64"),
                cols[3]: near_dead.astype("float64"),
                cols[4]: dead_expand.astype("float64"),
                cols[5]: golden_expand.astype("float64"),
                cols[6]: gap,
                cols[7]: gap_slope,
                cols[8]: gap_pct,
                cols[9]: green_narrow.astype("float64"),
                cols[10]: red_narrow.astype("float64"),
            },
            index=frame.index,
        )


__all__ = ["MACDStateIndicator"]
