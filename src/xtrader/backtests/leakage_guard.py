"""Utilities for guarding against common look-ahead leakage patterns."""

from __future__ import annotations

import pandas as pd


def find_unclosed_bar_violations(
    frame: pd.DataFrame,
    *,
    asof_ms: int,
    close_time_col: str = "close_time_ms",
) -> pd.DataFrame:
    """Return rows that are not closed by the given as-of timestamp.

    A bar is considered unsafe if `close_time_ms` is missing or strictly greater
    than `asof_ms`.
    """
    if close_time_col not in frame.columns:
        raise ValueError(f"missing required column: {close_time_col}")
    close_time = pd.to_numeric(frame[close_time_col], errors="coerce")
    mask = close_time.isna() | (close_time > int(asof_ms))
    return frame.loc[mask].copy()


def find_execution_lag_violations(
    frame: pd.DataFrame,
    *,
    interval_ms: int,
    min_lag_bars: int = 1,
    signal_time_col: str = "signal_time_ms",
    execution_time_col: str = "execution_time_ms",
) -> pd.DataFrame:
    """Return rows that violate minimum execution lag from signal time.

    Violation rule:
    - `execution_time_ms` is missing, or
    - `execution_time_ms - signal_time_ms < interval_ms * min_lag_bars`.
    """
    if interval_ms <= 0:
        raise ValueError("interval_ms must be greater than zero")
    if min_lag_bars < 1:
        raise ValueError("min_lag_bars must be at least 1")
    for column in (signal_time_col, execution_time_col):
        if column not in frame.columns:
            raise ValueError(f"missing required column: {column}")

    signal_time = pd.to_numeric(frame[signal_time_col], errors="coerce")
    execution_time = pd.to_numeric(frame[execution_time_col], errors="coerce")
    min_gap = int(interval_ms) * int(min_lag_bars)
    mask = signal_time.isna() | execution_time.isna() | ((execution_time - signal_time) < min_gap)
    return frame.loc[mask].copy()
