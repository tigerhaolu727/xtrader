from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from xtrader.strategies import ProfileActionStrategy, StrategyContext
from xtrader.strategies.feature_engine.pipeline import FeaturePipeline


def _bars_5m(rows: int = 420) -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=rows, freq="5min", tz="UTC")
    close = pd.Series([100.0 + (i * 0.23) + ((i % 9) - 4) * 0.11 for i in range(rows)], dtype="float64")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * rows,
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.3,
            "close": close,
            "volume": [1100.0 + ((i * 13) % 170) for i in range(rows)],
        }
    )


def _payload() -> dict[str, object]:
    return json.loads(
        Path("configs/strategy-profiles/five_min_regime_momentum/v0.3.json").read_text(encoding="utf-8")
    )


def test_profile_action_strategy_e2e_smoke_positive() -> None:
    strategy = ProfileActionStrategy()
    context = StrategyContext(
        as_of_time=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
        universe=("BTCUSDT",),
        inputs={"5m": _bars_5m()},
        meta={"account_context": {"equity": 10_000.0, "open_positions": 0, "daily_pnl_pct": 0.0}},
    )
    result = strategy.generate_actions(context)
    assert len(result.actions.index) == 420
    assert list(result.actions.columns) == [
        "timestamp",
        "symbol",
        "action",
        "size",
        "stop_loss",
        "take_profit",
        "reason",
    ]
    assert set(result.actions["action"].unique()).issubset({"ENTER_LONG", "ENTER_SHORT", "EXIT", "HOLD"})


def test_profile_action_strategy_diagnostics_positive() -> None:
    strategy = ProfileActionStrategy()
    context = StrategyContext(
        as_of_time=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
        universe=("BTCUSDT",),
        inputs={"5m": _bars_5m(rows=120)},
        meta={"account_context": {"equity": 5_000.0}},
    )
    result = strategy.generate_actions(context)
    diagnostics = result.diagnostics
    assert {"input_rows", "output_rows", "state_distribution", "action_distribution", "diagnostics_columns", "preview"}.issubset(
        set(diagnostics)
    )
    assert set(diagnostics["diagnostics_columns"]) >= {"state", "score_total", "action", "reason"}
    preview = diagnostics["preview"]
    assert isinstance(preview, list)
    assert preview
    assert {"state", "score_total", "action", "reason"}.issubset(set(preview[0]))


def test_profile_action_strategy_invalid_profile_negative() -> None:
    broken = copy.deepcopy(_payload())
    del broken["signal_spec"]["reason_code_map"]["long_breakout_v1"]
    with pytest.raises(ValueError, match=r"XTRSP007::PROFILE_PRECOMPILE_FAILED::MISSING_REASON_CODE_MAPPING::"):
        ProfileActionStrategy(profile_config=broken)


def test_profile_action_strategy_avoids_second_feature_build_for_trace() -> None:
    class _CountingPipeline(FeaturePipeline):
        def __init__(self) -> None:
            super().__init__()
            self.build_model_df_calls = 0

        def build_model_df(self, *, bars_df: pd.DataFrame, indicator_plan: list[dict[str, object]]) -> pd.DataFrame:
            self.build_model_df_calls += 1
            return super().build_model_df(bars_df=bars_df, indicator_plan=indicator_plan)

    strategy = ProfileActionStrategy()
    counting_pipeline = _CountingPipeline()
    strategy._feature_pipeline = counting_pipeline
    context = StrategyContext(
        as_of_time=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
        universe=("BTCUSDT",),
        inputs={"5m": _bars_5m(rows=120)},
        meta={"account_context": {"equity": 5_000.0}},
    )
    strategy.generate_actions(context)
    assert counting_pipeline.build_model_df_calls == len(strategy._required_timeframes)
