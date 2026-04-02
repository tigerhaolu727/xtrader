import pandas as pd
import pytest

from xtrader.backtests import find_execution_lag_violations, find_unclosed_bar_violations


def test_find_unclosed_bar_violations() -> None:
    frame = pd.DataFrame(
        [
            {"close_time_ms": 1_000, "value": 1},
            {"close_time_ms": 2_000, "value": 2},
            {"close_time_ms": None, "value": 3},
        ]
    )
    violations = find_unclosed_bar_violations(frame, asof_ms=1_500)
    assert len(violations.index) == 2
    assert set(violations["value"].tolist()) == {2, 3}


def test_find_execution_lag_violations() -> None:
    frame = pd.DataFrame(
        [
            {"signal_time_ms": 1_000, "execution_time_ms": 1_500, "id": "bad_short_lag"},
            {"signal_time_ms": 1_000, "execution_time_ms": 2_000, "id": "ok"},
            {"signal_time_ms": 1_000, "execution_time_ms": None, "id": "bad_missing"},
        ]
    )
    violations = find_execution_lag_violations(
        frame,
        interval_ms=1_000,
        min_lag_bars=1,
    )
    assert len(violations.index) == 2
    assert set(violations["id"].tolist()) == {"bad_short_lag", "bad_missing"}


def test_find_execution_lag_violations_requires_columns() -> None:
    frame = pd.DataFrame([{"signal_time_ms": 1_000}])
    with pytest.raises(ValueError, match="missing required column: execution_time_ms"):
        find_execution_lag_violations(frame, interval_ms=1_000)
